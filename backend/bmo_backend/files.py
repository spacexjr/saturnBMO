"""Gerenciamento de arquivos confinado a uma pasta autorizada.

Toda operação passa por :class:`Workspace`. O modelo nunca recebe acesso ao
sistema de arquivos inteiro: caminhos são resolvidos e comparados com a raiz
autorizada, incluindo links simbólicos (``Path.resolve`` segue o link antes da
comparação).
"""

from __future__ import annotations

import json
import os
import platform
import shutil
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .config import DATA_DIR

ACCESS_FILE = DATA_DIR / "access.json"
MAX_READ_BYTES = 512 * 1024
MAX_WRITE_CHARS = 512 * 1024


class WorkspaceError(RuntimeError):
    pass


@dataclass
class AccessState:
    path: str = ""
    os: str = ""
    selected_at: str = ""
    authorized: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "os": self.os,
            "selected_at": self.selected_at,
            "authorized": self.authorized,
        }


class Workspace:
    def __init__(self, access_file: Path | None = None) -> None:
        self.access_file = access_file or ACCESS_FILE
        self.state = self._load()

    # -- autorização ------------------------------------------------------

    def _load(self) -> AccessState:
        if not self.access_file.exists():
            return AccessState(os=platform.system())
        try:
            raw = json.loads(self.access_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return AccessState(os=platform.system())
        path = str(raw.get("path", ""))
        authorized = bool(raw.get("authorized", False))
        if authorized and path and not Path(path).is_dir():
            authorized = False
        return AccessState(
            path=path,
            os=str(raw.get("os", platform.system())),
            selected_at=str(raw.get("selected_at", "")),
            authorized=authorized,
        )

    def _save(self) -> None:
        self.access_file.parent.mkdir(parents=True, exist_ok=True)
        self.access_file.write_text(
            json.dumps(self.state.as_dict(), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        try:
            self.access_file.chmod(0o600)
        except OSError:
            pass

    def authorize(self, path: str) -> AccessState:
        candidate = Path(path).expanduser()
        try:
            resolved = candidate.resolve(strict=True)
        except OSError as exc:
            raise WorkspaceError(f"Pasta inválida: {path}") from exc
        if not resolved.is_dir():
            raise WorkspaceError(f"O caminho não é uma pasta: {path}")
        self.state = AccessState(
            path=str(resolved),
            os=platform.system(),
            selected_at=time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            authorized=True,
        )
        self._save()
        return self.state

    def revoke(self) -> AccessState:
        self.state.authorized = False
        self._save()
        return self.state

    def status(self) -> dict[str, Any]:
        return self.state.as_dict()

    @property
    def root(self) -> Path | None:
        if not self.state.authorized or not self.state.path:
            return None
        return Path(self.state.path)

    def require_root(self) -> Path:
        root = self.root
        if root is None:
            raise WorkspaceError(
                "Nenhuma pasta autorizada. Peça ao usuário para escolher uma pasta em "
                "Ajustes, seção 'Pasta de acesso do BMO'."
            )
        return root

    # -- caminhos ---------------------------------------------------------

    def resolve(self, path: str | None) -> Path:
        root = self.require_root()
        raw = (path or "").strip()
        if not raw or raw in {".", "./"}:
            target = root
        else:
            candidate = Path(raw).expanduser()
            target = candidate if candidate.is_absolute() else root / candidate
        try:
            resolved = target.resolve(strict=False)
        except OSError as exc:
            raise WorkspaceError(f"Caminho inválido: {path}") from exc
        try:
            common = os.path.commonpath([str(root), str(resolved)])
        except ValueError as exc:
            raise WorkspaceError("Caminho fora da pasta autorizada.") from exc
        if common != str(root):
            raise WorkspaceError(
                "Acesso negado: o caminho fica fora da pasta autorizada do BMO."
            )
        return resolved

    def display(self, path: Path) -> str:
        root = self.root
        if root is None:
            return str(path)
        try:
            return str(path.relative_to(root)) or "."
        except ValueError:
            return str(path)

    # -- leitura ----------------------------------------------------------

    def list_files(self, path: str | None = None, limit: int = 200) -> dict[str, Any]:
        target = self.resolve(path)
        if not target.exists():
            raise WorkspaceError(f"Pasta não encontrada: {path}")
        if not target.is_dir():
            return {"path": self.display(target), "entries": [self._entry(target)]}
        entries = []
        for child in sorted(target.iterdir(), key=lambda item: (not item.is_dir(), item.name.lower())):
            if len(entries) >= max(1, min(limit, 1000)):
                break
            entries.append(self._entry(child))
        return {"path": self.display(target), "entries": entries}

    def _entry(self, item: Path) -> dict[str, Any]:
        try:
            stat = item.stat()
            size = stat.st_size
            modified = time.strftime("%Y-%m-%d %H:%M", time.localtime(stat.st_mtime))
        except OSError:
            size = None
            modified = None
        return {
            "name": item.name,
            "path": self.display(item),
            "type": "directory" if item.is_dir() else "file",
            "size": size,
            "modified": modified,
            "is_symlink": item.is_symlink(),
        }

    def search_files(
        self,
        query: str,
        path: str | None = None,
        content: bool = False,
        limit: int = 50,
    ) -> dict[str, Any]:
        target = self.resolve(path)
        if not target.is_dir():
            raise WorkspaceError(f"Pesquisa requer uma pasta: {path}")
        needle = (query or "").strip()
        if not needle:
            raise WorkspaceError("Informe um nome ou trecho para pesquisar.")
        candidates = target.rglob("*") if content else target.rglob(f"*{needle}*")
        matches: list[dict[str, Any]] = []
        max_matches = max(1, min(limit, 200))
        for candidate in candidates:
            if len(matches) >= max_matches:
                break
            # Nunca leia além da raiz autorizada, mesmo através de links.
            try:
                self.resolve(str(candidate))
            except WorkspaceError:
                continue
            name_match = needle.lower() in candidate.name.lower()
            if candidate.is_dir():
                if name_match:
                    matches.append(self._entry(candidate))
                continue
            content_match = False
            if content and candidate.is_file():
                try:
                    if candidate.stat().st_size <= MAX_READ_BYTES:
                        text = candidate.read_text(encoding="utf-8", errors="ignore")
                        content_match = needle.lower() in text.lower()
                except OSError:
                    content_match = False
            if not name_match and not content_match:
                continue
            entry = self._entry(candidate)
            if content_match:
                entry["match"] = "conteúdo"
            matches.append(entry)
        return {"path": self.display(target), "query": needle, "entries": matches}

    def read_file(self, path: str) -> dict[str, Any]:
        target = self.resolve(path)
        if not target.is_file():
            raise WorkspaceError(f"Arquivo não encontrado: {path}")
        if target.stat().st_size > MAX_READ_BYTES:
            raise WorkspaceError("Arquivo grande demais para leitura direta (limite de 512 KiB).")
        data = target.read_bytes()
        if b"\x00" in data[:4096]:
            return {
                "path": self.display(target),
                "binary": True,
                "size": len(data),
                "message": "Arquivo binário; conteúdo não exibido.",
            }
        return {
            "path": self.display(target),
            "binary": False,
            "content": data.decode("utf-8", errors="replace"),
            "size": len(data),
        }

    def get_file_metadata(self, path: str) -> dict[str, Any]:
        target = self.resolve(path)
        if not target.exists():
            raise WorkspaceError(f"Caminho não encontrado: {path}")
        stat = target.stat()
        return {
            "path": self.display(target),
            "absolute_path": str(target),
            "name": target.name,
            "type": "directory" if target.is_dir() else "file",
            "size": stat.st_size,
            "modified": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(stat.st_mtime)),
            "created": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(stat.st_ctime)),
            "is_symlink": target.is_symlink(),
            "extension": target.suffix,
        }

    # -- escrita ----------------------------------------------------------

    def create_file(self, path: str, content: str = "") -> dict[str, Any]:
        target = self.resolve(path)
        if target.exists():
            raise WorkspaceError("O arquivo já existe. Use write_file para sobrescrever.")
        if not target.parent.exists():
            raise WorkspaceError("A pasta de destino não existe. Crie a pasta primeiro.")
        self._check_content(content)
        target.write_text(content, encoding="utf-8")
        return {"ok": True, "path": self.display(target), "bytes": len(content.encode("utf-8"))}

    def write_file(self, path: str, content: str) -> dict[str, Any]:
        target = self.resolve(path)
        if not target.exists():
            raise WorkspaceError("O arquivo não existe. Use create_file para criar.")
        if target.is_dir():
            raise WorkspaceError("O caminho é uma pasta, não um arquivo.")
        self._check_content(content)
        target.write_text(content, encoding="utf-8")
        return {"ok": True, "path": self.display(target), "bytes": len(content.encode("utf-8"))}

    def edit_file(self, path: str, old_text: str, new_text: str) -> dict[str, Any]:
        if not old_text:
            raise WorkspaceError("Informe o trecho exato a ser substituído.")
        target = self.resolve(path)
        if not target.is_file():
            raise WorkspaceError(f"Arquivo não encontrado: {path}")
        original = target.read_text(encoding="utf-8", errors="strict")
        count = original.count(old_text)
        if count == 0:
            raise WorkspaceError("O trecho informado não foi encontrado no arquivo.")
        if count > 1:
            raise WorkspaceError(
                "O trecho aparece mais de uma vez. Use um trecho maior e único."
            )
        self._check_content(new_text)
        updated = original.replace(old_text, new_text, 1)
        target.write_text(updated, encoding="utf-8")
        return {"ok": True, "path": self.display(target), "replacements": 1}

    def create_directory(self, path: str) -> dict[str, Any]:
        target = self.resolve(path)
        target.mkdir(parents=True, exist_ok=False)
        return {"ok": True, "path": self.display(target), "type": "directory"}

    def rename_file(self, path: str, new_name: str) -> dict[str, Any]:
        target = self.resolve(path)
        if not target.exists():
            raise WorkspaceError(f"Caminho não encontrado: {path}")
        clean = Path(new_name).name
        if not clean or clean in {".", ".."} or clean != new_name.strip():
            raise WorkspaceError("O novo nome deve ser um nome simples, sem barras.")
        destination = self.resolve(str(Path(self.display(target)).parent / clean))
        if destination.exists():
            raise WorkspaceError("Já existe um item com esse nome.")
        target.rename(destination)
        return {"ok": True, "from": self.display(target), "to": self.display(destination)}

    def copy_file(self, source: str, destination: str) -> dict[str, Any]:
        src = self.resolve(source)
        dst = self.resolve(destination)
        if not src.exists():
            raise WorkspaceError(f"Origem não encontrada: {source}")
        if dst.exists() and dst.is_dir():
            dst = dst / src.name
        if dst.exists():
            raise WorkspaceError("O destino já existe.")
        if src.is_dir():
            shutil.copytree(src, dst)
        else:
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
        return {"ok": True, "from": self.display(src), "to": self.display(dst)}

    def move_file(self, source: str, destination: str) -> dict[str, Any]:
        src = self.resolve(source)
        dst = self.resolve(destination)
        if not src.exists():
            raise WorkspaceError(f"Origem não encontrada: {source}")
        if dst.exists() and dst.is_dir():
            dst = dst / src.name
        if dst.exists():
            raise WorkspaceError("O destino já existe.")
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(src), str(dst))
        return {"ok": True, "from": self.display(src), "to": self.display(dst)}

    def delete_file(self, path: str) -> dict[str, Any]:
        target = self.resolve(path)
        if not target.exists():
            raise WorkspaceError(f"Arquivo não encontrado: {path}")
        if target.is_dir():
            raise WorkspaceError("O caminho é uma pasta. Use delete_directory.")
        target.unlink()
        return {"ok": True, "path": self.display(target), "deleted": "file"}

    def delete_directory(self, path: str, recursive: bool = False) -> dict[str, Any]:
        target = self.resolve(path)
        if not target.exists():
            raise WorkspaceError(f"Pasta não encontrada: {path}")
        if not target.is_dir():
            raise WorkspaceError("O caminho é um arquivo. Use delete_file.")
        if target == self.root:
            raise WorkspaceError("Não é permitido excluir a própria pasta autorizada.")
        if recursive:
            shutil.rmtree(target)
        else:
            target.rmdir()
        return {"ok": True, "path": self.display(target), "deleted": "directory"}

    def _check_content(self, content: str) -> None:
        if len(content) > MAX_WRITE_CHARS:
            raise WorkspaceError("Conteúdo grande demais para escrita (limite de 512 KiB).")
