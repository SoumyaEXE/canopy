@echo off
rem Overnight queue: fast, balanced, high-accuracy. Each is time-capped so it always ends with saved weights.
cd /d "%~dp0.."
.venv\Scripts\python.exe scripts\train_trees.py --variant yolo11n-seg --epochs 200 --time 1.0 --batch 8
.venv\Scripts\python.exe scripts\train_trees.py --variant yolo11s-seg --epochs 200 --time 2.0 --batch 8
.venv\Scripts\python.exe scripts\train_trees.py --variant yolo11m-seg --epochs 200 --time 3.5 --batch 4
