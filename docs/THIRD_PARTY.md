# Third-party software and licenses

The app uses open-source Python libraries. The executable created by PyInstaller includes Python runtime components and installed dependencies. Their original licenses remain in effect; the repository's MIT license applies to the project's own source code only.

Runtime dependencies (see `requirements.txt` for actual version constraints and dependency trees):

- [UnityPy](https://github.com/K0lb3/UnityPy)
- [PySide6 / Qt for Python](https://doc.qt.io/qtforpython-6/)
- [PyVista](https://github.com/pyvista/pyvista)
- [PyVistaQt](https://github.com/pyvista/pyvistaqt)
- [VTK](https://vtk.org/)
- [Trimesh](https://github.com/mikedh/trimesh)
- [NumPy](https://numpy.org/)
- [Pillow](https://python-pillow.org/)
- [pyuepak](https://pypi.org/project/pyuepak/)
- [cryptography](https://cryptography.io/)

Build-only tools:

- [PyInstaller](https://pyinstaller.org/)
- [GitHub Actions](https://docs.github.com/en/actions)

**Proprietary runtime note:** pyuepak may fetch the Oodle codec DLL the first time it is used. The public Windows EXE does **not bundle Oodle**. It prepares pyuepak's temporary extraction folder and caches the upstream SHA-256-verified DLL locally across launches. Review the Oodle and original redistribution terms before using it.

**Not bundled**: [UE Viewer (UModel)](https://www.gildor.org/en/projects/umodel) and [Blender](https://www.blender.org/). Users must obtain them separately and comply with their terms. Neither program is part of the `.exe`.

Maintainers distributing binaries should review and fulfill all third-party license-notice and redistribution requirements for the exact resolved wheel versions (including Qt/PySide6 and VTK dependencies), and audit security updates before each public release. No game archives, third-party assets, or AES keys may be included in releases.
