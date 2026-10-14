"""Disable UnityPy's unused native FMOD audio dependency in the Windows EXE.

UnityPy.export/__init__.py eagerly imports AudioClipConverter even when only
Texture2DConverter is needed. AudioClipConverter imports fmod_toolkit, whose
import loads the proprietary FMOD DLL at once. This application supports mesh
and texture preview/export, NOT AudioClip conversion, so installing this tiny
stub before the application's imports avoids shipping an unnecessary FMOD DLL.

This is a PyInstaller *runtime hook*. Normal Python-source installations
are unaffected, and audio extraction remains explicitly unsupported in EXEs.
"""
import sys
import types

if not sys.modules.get("fmod_toolkit"):
    _optional_audio = types.ModuleType("fmod_toolkit")
    _optional_audio._meab_optional_audio_disabled = True

    def _unsupported_audio(*args, **kwargs):
        raise RuntimeError(
            "Unity AudioClip conversion is not supported by Multi-Engine Asset Browser. "
            "Only mesh and texture preview/export are available."
        )

    _optional_audio.raw_to_wav = _unsupported_audio
    sys.modules["fmod_toolkit"] = _optional_audio
