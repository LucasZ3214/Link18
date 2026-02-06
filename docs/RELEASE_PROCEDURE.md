# Link18 Release Procedure

This document outlines the standard process for creating and publishing a new release of Link18.

## 1. Preparation
- **Verify Version**: Ensure the version number in `main.py` (if any), `README.md`, and `docs/DEVELOPMENT.md` is updated.
- **Sync Code**: Ensure all changes are committed and your working directory is clean.

## 2. Rebuild Executable
The executable must be rebuilt whenever `main.py` or core logic changes.
```powershell
# In the project root
.\venv\Scripts\python.exe -m PyInstaller Link18.spec --noconfirm
```
Verify that `dist/Link18.exe` has been updated with a current timestamp.

## 3. Update Release Script
Update `create_release.py` to reflect the new version number in the `release_name` variable:
```python
release_name = "Link18_v1.X.Y.zip"
```

## 4. Run Release Script
Execute the packaging script to generate the sanitized zip file:
```powershell
.\venv\Scripts\python.exe create_release.py
```
This generates `Link18_v1.X.Y.zip` in the root directory.

## 5. Git Tagging & Push
Mark the release in version control:
```powershell
git add -A
git commit -m "v1.X.Y - Release"
git push origin main

# Create and push the tag
git tag v1.X.Y
git push origin v1.X.Y
```

## 6. GitHub Release
1. Go to the [Link18 Releases page](https://github.com/LucasZ3214/Link18/releases).
2. "Draft a new release".
3. Select the tag `v1.X.Y`.
4. Copy the "What's New" section from `README.md` into the description.
5. Upload the generated `Link18_v1.X.Y.zip` as a binary asset.
6. Publish.
