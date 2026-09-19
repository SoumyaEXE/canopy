"""Google Colab CLI Training Script for YOLO11m-seg (Tree Crown Segmentation).

This script is self-contained for execution on Google Colab GPU runtimes.
"""

import os
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

def setup_environment():
    print("[*] Installing required packages on Colab runtime...")
    os.system("pip install -q ultralytics shapely pillow numpy matplotlib rasterio pyproj")

def main():
    setup_environment()
    
    from ultralytics import YOLO
    
    print("\n=======================================================")
    print("[*] Initializing YOLO11m-seg (Medium Instance Segmentation)...")
    print("=======================================================")
    
    model = YOLO("yolo11m-seg.pt")
    
    print(f"[+] Model loaded successfully: {model}")
    print("[+] Ready for fine-tuning / dataset execution.")

if __name__ == "__main__":
    main()
