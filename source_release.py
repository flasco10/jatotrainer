"""Make the corresponding-source archive to publish with the installer."""
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

root = Path(__file__).resolve().parent
out = root / "installer-output" / "jatotrainer-corresponding-source.zip"
out.parent.mkdir(exist_ok=True)
omit = {"build", "build-tools", "dist", "installer-output", "__pycache__", "bin", "obj"}
with ZipFile(out, "w", ZIP_DEFLATED) as archive:
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root)
        if any(part in omit or part.startswith(".") for part in relative.parts):
            continue
        if path.is_file() and path.suffix.lower() not in {".exe", ".dll", ".pdb", ".pyc", ".whl"}:
            archive.write(path, Path("jatotrainer") / relative)
print(out)
