# 🚀 Fast Dash Demo Applications

A collection of interactive web applications showcasing the power and simplicity of Fast Dash.

## 📋 What's Included

This demo package includes **4 fully functional web applications** built with Fast Dash:

### 1. 📊 Data Insights Dashboard
An interactive data visualization tool featuring:
- Multiple sample datasets (Sales, Weather, Stocks, Customer Analytics)
- 4 chart types (Line, Bar, Scatter, Pie)
- Customizable color themes
- Live data table display
- Automatic statistical summaries

### 2. 📝 Text Analyzer Pro
A comprehensive text analysis tool with:
- Real-time word and character counting
- Text transformations (uppercase, lowercase, title case, reverse)
- Word length distribution visualization
- Vocabulary richness analysis
- Most common words detection

### 3. 🎨 Image Processor Studio
Professional image processing application:
- Upload any image format
- Apply effects (Blur, Sharpen, Edge Enhance, Emboss, Grayscale)
- Brightness adjustment (50% - 150%)
- Image rotation (0° - 360°)
- Detailed processing information

### 4. 🔢 Smart Calculator & Converter
Multi-purpose calculation tool:
- Basic operations (Add, Subtract, Multiply, Divide, Power)
- Temperature conversion (Celsius, Fahrenheit, Kelvin)
- Length conversion (Meters, Feet, Miles, Kilometers)
- Visual representation of results
- Real-time calculations

## 🎯 Quick Start

### Option 1: Interactive Launcher (Recommended)

```bash
python run_demo.py
```

Then select which demo you want to run (1-4).

### Option 2: Command Line

```bash
# Run a specific demo directly
python run_demo.py 1  # Data Dashboard
python run_demo.py 2  # Text Analyzer
python run_demo.py 3  # Image Processor
python run_demo.py 4  # Calculator
```

### Option 3: Run Individual Demos

```bash
# Edit demo_app.py and uncomment the demo you want:
python demo_app.py
```

## 🌐 Accessing the Apps

Once started, open your browser and navigate to:
```
http://127.0.0.1:8080/
```

Press `Ctrl+C` in the terminal to stop the server.

## 📦 Requirements

These demos require:
```
fast-dash
pandas
numpy
plotly
Pillow
```

All dependencies are already included if you have Fast Dash installed.

## 🎨 Features Demonstrated

These demos showcase Fast Dash's key capabilities:

### Type Hint Magic
```python
def my_app(
    text: str = "default",           # Text input
    number: int = range(0, 100),     # Slider
    choice: str = ["A", "B", "C"],   # Dropdown
    image: Image.Image = None        # Image upload
) -> go.Figure:                       # Plotly graph output
    pass
```

### Multiple Input/Output Types
- ✅ Text and TextArea
- ✅ Numeric sliders with ranges
- ✅ Dropdown selections
- ✅ File/Image uploads
- ✅ Plotly graphs
- ✅ DataFrames/Tables
- ✅ Images (PIL)

### Customization Options
- 🎨 10+ built-in themes
- 🔗 GitHub integration
- 📝 Custom titles and subheaders
- 🎯 Markdown support in outputs

## 💡 Learn More

Each demo function includes comprehensive docstrings and comments.
Open `demo_app.py` to see the implementation details.

### Key Concepts Shown:

1. **Simple Decorator Pattern**
   ```python
   @fastdash(title="My App", theme="FLATLY")
   def my_function(input: str) -> str:
       return input.upper()
   ```

2. **Type-Driven UI Generation**
   - Function parameters → Input components
   - Return type hints → Output components
   - Default values → Component properties

3. **Multiple Outputs**
   ```python
   def multi_output() -> (str, go.Figure, pd.DataFrame):
       return "text", figure, dataframe
   ```

4. **Rich Data Types**
   - Plotly figures for interactive charts
   - Pandas DataFrames for tables
   - PIL Images for image processing
   - Basic types for text/numbers

## 🔧 Customization

Feel free to modify any demo:

1. Change themes: `theme="JOURNAL"`, `"SKETCHY"`, `"FLATLY"`, etc.
2. Add your GitHub URL: `github_url="https://github.com/yourusername/repo"`
3. Modify input ranges and options
4. Add new features to existing demos
5. Create entirely new demos using the same patterns

## 📚 Documentation

For more information about Fast Dash:
- GitHub: https://github.com/dkedar7/fast_dash
- Documentation: Check the `/docs` folder
- PyPI: https://pypi.org/project/fast-dash/

## 🎓 What Makes This Special?

These demos show how Fast Dash enables you to:

1. **Build apps in minutes, not hours**
   - No HTML/CSS/JavaScript needed
   - No complex callbacks to write
   - Pure Python with type hints

2. **Focus on functionality**
   - Write your logic
   - Add `@fastdash` decorator
   - Done!

3. **Create professional UIs**
   - Modern, responsive designs
   - Interactive components
   - Mobile-friendly layouts

4. **Deploy anywhere**
   - Local development
   - Cloud platforms (Google Cloud, AWS)
   - Docker containers
   - Jupyter notebooks

## 🚀 Next Steps

Try modifying the demos:
- Change the color schemes
- Add new data sources
- Implement your own algorithms
- Combine features from multiple demos

Happy building! 🎉

---

Built with ❤️ using [Fast Dash](https://github.com/dkedar7/fast_dash)
