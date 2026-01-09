#!/usr/bin/env python3
"""
Test script for the resizable sidebar feature.
This creates a simple FastDash app with sidebar layout to test the drag functionality.
"""

from fast_dash import FastDash
from fast_dash.Components import Text, Slider

def text_with_slider(input_text, slider_value):
    """Simple callback function for testing"""
    return f"{input_text}. Slider value: {slider_value}"

# Create app with sidebar layout
app = FastDash(
    callback_fn=text_with_slider,
    inputs=[Text, Slider],
    outputs=Text,
    title="Resizable Sidebar Test",
    layout="sidebar"  # This is the key parameter for sidebar layout
)

if __name__ == "__main__":
    print("Starting test app with resizable sidebar...")
    print("Instructions:")
    print("1. Open the app in your browser")
    print("2. Look for the sidebar on the left")
    print("3. Hover over the right edge of the sidebar")
    print("4. You should see a blue highlight and col-resize cursor")
    print("5. Click and drag to resize the sidebar")
    print("6. Maximum width is 50% of the screen")
    print("7. Minimum width is 150px")
    print("8. Width is saved to localStorage")
    app.run()
