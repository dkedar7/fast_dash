#!/usr/bin/env python3
"""
Fast Dash Demo Launcher
=======================
Easy launcher for all Fast Dash demo applications.
"""

import sys
from demo_app import (
    data_visualizer,
    text_analyzer,
    image_processor,
    calculator_converter
)


def main():
    demos = {
        "1": ("Data Insights Dashboard", data_visualizer),
        "2": ("Text Analyzer Pro", text_analyzer),
        "3": ("Image Processor Studio", image_processor),
        "4": ("Smart Calculator & Converter", calculator_converter),
        "all": ("Data Insights Dashboard", data_visualizer)  # Default
    }

    print("=" * 60)
    print("🚀 Fast Dash Demo Launcher")
    print("=" * 60)
    print("\nAvailable Demos:")
    print("  1. 📊 Data Insights Dashboard - Interactive data visualization")
    print("  2. 📝 Text Analyzer Pro - Comprehensive text analysis")
    print("  3. 🎨 Image Processor Studio - Image effects and transformations")
    print("  4. 🔢 Smart Calculator & Converter - Math and unit conversion")
    print("\n" + "=" * 60)

    if len(sys.argv) > 1:
        choice = sys.argv[1]
    else:
        choice = input("\nEnter demo number (1-4) or press Enter for default [1]: ").strip() or "1"

    if choice in demos:
        name, demo_fn = demos[choice]
        print(f"\n✨ Launching: {name}")
        print("📍 App will open at: http://127.0.0.1:8080/")
        print("\nPress Ctrl+C to stop the server.\n")
        demo_fn()
    else:
        print(f"\n❌ Invalid choice: {choice}")
        print("Please enter a number between 1-4")
        sys.exit(1)


if __name__ == "__main__":
    main()
