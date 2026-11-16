"""Acting voices: speech models that take direction. This package runs in its own environment
(vendor/acting/venv, built by tools/install_voice_tools.sh) and is never imported by `stopmo`;
the host runs `python -m stopmo_voice.speak jobs.json`, the same way it runs Blender.
"""
