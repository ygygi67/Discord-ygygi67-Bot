@echo off
call .venv\Scripts\activate.bat
pip install pyvirtualcam keyboard playwright

title Virtual_Camera

python Virtual_Camera.py
pause