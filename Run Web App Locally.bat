@echo off
rem Runs the web version on this PC only, to test changes before they go online.
rem Your browser opens http://localhost:8501 - close this window to stop it.
cd /d "%~dp0"
py -m streamlit run streamlit_app.py --server.address localhost --server.port 8501 %*
