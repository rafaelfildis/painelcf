@echo off
REM Coleta diária do módulo de teses (Agendador de Tarefas do Windows).
REM Ajuste PAINELCF para a pasta onde o repositório foi clonado.
set PAINELCF=C:\painelcf
cd /d %PAINELCF%
python -m painelcf.teses diario >> dados\coleta.log 2>&1
