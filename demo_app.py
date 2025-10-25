"""
Fast Dash Demo: Data Insights Dashboard
========================================
A comprehensive demo showcasing fast_dash capabilities:
- Data visualization with interactive charts
- Text analysis tools
- Image processing
- Multiple input types (text, sliders, dropdowns, file uploads)
- Multiple output types (graphs, tables, images, text)
"""

from fast_dash import fastdash
import pandas as pd
import plotly.graph_objects as go
import plotly.express as px
from PIL import Image, ImageEnhance, ImageFilter
import numpy as np
from datetime import datetime
import io


# ============================================================================
# Demo 1: Interactive Data Visualizer
# ============================================================================

@fastdash(
    title="📊 Data Insights Dashboard",
    subheader="A powerful demo showcasing Fast Dash capabilities - from simple text analysis to complex visualizations",
    theme="FLATLY",
    github_url="https://github.com/dkedar7/fast_dash"
)
def data_visualizer(
    dataset: str = ["Sales Data", "Weather Data", "Stock Prices", "Customer Analytics"],
    chart_type: str = ["Line", "Bar", "Scatter", "Pie"],
    num_points: int = range(10, 100, 10),
    color_theme: str = ["Viridis", "Plotly", "Sunset", "Ocean"]
) -> (go.Figure, pd.DataFrame, str):
    """
    Interactive Data Visualization Tool

    Generate beautiful visualizations from sample datasets with customizable parameters.
    Choose your dataset, chart type, and styling to explore the data!
    """

    # Generate sample data based on selection
    if dataset == "Sales Data":
        dates = pd.date_range(start='2024-01-01', periods=num_points, freq='D')
        data = pd.DataFrame({
            'Date': dates,
            'Revenue': np.random.randint(1000, 5000, num_points),
            'Costs': np.random.randint(500, 2000, num_points),
            'Profit': np.random.randint(200, 1500, num_points)
        })
        title = "Sales Performance Over Time"

    elif dataset == "Weather Data":
        dates = pd.date_range(start='2024-01-01', periods=num_points, freq='D')
        data = pd.DataFrame({
            'Date': dates,
            'Temperature': np.random.randint(10, 35, num_points),
            'Humidity': np.random.randint(30, 90, num_points),
            'Wind Speed': np.random.randint(0, 30, num_points)
        })
        title = "Weather Conditions"

    elif dataset == "Stock Prices":
        dates = pd.date_range(start='2024-01-01', periods=num_points, freq='D')
        base_price = 100
        returns = np.random.randn(num_points) * 2
        prices = base_price + np.cumsum(returns)
        data = pd.DataFrame({
            'Date': dates,
            'Open': prices + np.random.randn(num_points) * 0.5,
            'Close': prices,
            'Volume': np.random.randint(1000000, 5000000, num_points)
        })
        title = "Stock Price Movement"

    else:  # Customer Analytics
        data = pd.DataFrame({
            'Customer Segment': ['New', 'Returning', 'VIP', 'Inactive'],
            'Count': np.random.randint(50, 500, 4),
            'Revenue': np.random.randint(5000, 50000, 4),
            'Satisfaction': np.random.randint(60, 100, 4)
        })
        title = "Customer Segments Analysis"

    # Create visualization based on chart type
    color_map = {
        "Viridis": px.colors.sequential.Viridis,
        "Plotly": px.colors.qualitative.Plotly,
        "Sunset": px.colors.sequential.Sunset,
        "Ocean": px.colors.sequential.Teal
    }

    if chart_type == "Line":
        fig = go.Figure()
        for col in data.select_dtypes(include=[np.number]).columns:
            fig.add_trace(go.Scatter(
                x=data[data.columns[0]],
                y=data[col],
                mode='lines+markers',
                name=col
            ))
    elif chart_type == "Bar":
        fig = go.Figure()
        for col in data.select_dtypes(include=[np.number]).columns:
            fig.add_trace(go.Bar(
                x=data[data.columns[0]],
                y=data[col],
                name=col
            ))
    elif chart_type == "Scatter":
        numeric_cols = data.select_dtypes(include=[np.number]).columns
        if len(numeric_cols) >= 2:
            fig = px.scatter(
                data,
                x=numeric_cols[0],
                y=numeric_cols[1],
                color=numeric_cols[0] if len(numeric_cols) > 0 else None,
                size=numeric_cols[1] if len(numeric_cols) > 1 else None,
                color_continuous_scale=color_theme.lower()
            )
        else:
            fig = go.Figure()
            fig.add_annotation(text="Not enough numeric columns for scatter plot", showarrow=False)
    else:  # Pie
        numeric_cols = data.select_dtypes(include=[np.number]).columns
        if len(numeric_cols) > 0:
            fig = go.Figure(data=[go.Pie(
                labels=data[data.columns[0]] if not data[data.columns[0]].dtype in [np.number] else data.index,
                values=data[numeric_cols[0]],
                marker=dict(colors=color_map[color_theme])
            )])
        else:
            fig = go.Figure()

    fig.update_layout(
        title=title,
        template="plotly_white",
        height=500
    )

    # Generate summary statistics
    summary = f"""
    📈 **Dataset Summary**

    - **Dataset**: {dataset}
    - **Chart Type**: {chart_type}
    - **Data Points**: {len(data)}
    - **Columns**: {', '.join(data.columns)}

    **Quick Stats:**
    - Total Records: {len(data)}
    - Numeric Columns: {len(data.select_dtypes(include=[np.number]).columns)}
    - Generated at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
    """

    return fig, data, summary


# ============================================================================
# Demo 2: Text Analyzer
# ============================================================================

@fastdash(
    title="📝 Text Analyzer Pro",
    subheader="Analyze your text with comprehensive statistics and insights",
    theme="JOURNAL"
)
def text_analyzer(
    text: str = "Fast Dash makes building web apps incredibly easy! Try typing your own text here to see real-time analysis.",
    case_transform: str = ["Original", "UPPERCASE", "lowercase", "Title Case", "Reverse"]
) -> (str, str, go.Figure):
    """
    Advanced Text Analysis Tool

    Get detailed insights about your text including word count, character analysis,
    and visual word length distribution.
    """

    if not text:
        text = "Enter some text to analyze!"

    # Apply transformation
    if case_transform == "UPPERCASE":
        transformed = text.upper()
    elif case_transform == "lowercase":
        transformed = text.lower()
    elif case_transform == "Title Case":
        transformed = text.title()
    elif case_transform == "Reverse":
        transformed = text[::-1]
    else:
        transformed = text

    # Calculate statistics
    words = text.split()
    word_count = len(words)
    char_count = len(text)
    char_no_spaces = len(text.replace(" ", ""))
    sentence_count = text.count('.') + text.count('!') + text.count('?')
    avg_word_length = sum(len(word) for word in words) / max(word_count, 1)

    # Create word length distribution chart
    word_lengths = [len(word) for word in words]
    fig = go.Figure(data=[go.Histogram(
        x=word_lengths,
        nbinsx=max(word_lengths) if word_lengths else 1,
        marker_color='indianred'
    )])
    fig.update_layout(
        title="Word Length Distribution",
        xaxis_title="Word Length (characters)",
        yaxis_title="Frequency",
        template="plotly_white",
        height=400
    )

    # Generate analysis report
    analysis = f"""
    📊 **Text Analysis Report**

    **Basic Statistics:**
    - Words: {word_count}
    - Characters (with spaces): {char_count}
    - Characters (no spaces): {char_no_spaces}
    - Sentences: {sentence_count}
    - Average word length: {avg_word_length:.2f}

    **Unique Words:**
    - Unique words: {len(set(word.lower() for word in words))}
    - Vocabulary richness: {len(set(word.lower() for word in words)) / max(word_count, 1) * 100:.1f}%

    **Most Common Words:**
    {', '.join(sorted(set(words), key=lambda x: words.count(x), reverse=True)[:5])}
    """

    return transformed, analysis, fig


# ============================================================================
# Demo 3: Image Processor
# ============================================================================

@fastdash(
    title="🎨 Image Processor Studio",
    subheader="Upload and transform images with various filters and effects",
    theme="SKETCHY"
)
def image_processor(
    image: Image.Image,
    effect: str = ["Original", "Blur", "Sharpen", "Edge Enhance", "Emboss", "Grayscale"],
    brightness: float = range(50, 150, 10),
    rotation: int = range(0, 360, 45)
) -> (Image.Image, str):
    """
    Professional Image Processing Tool

    Upload any image and apply various effects, adjust brightness, and rotate.
    Perfect for quick image transformations!
    """

    if image is None:
        # Create a default colorful gradient image
        img_array = np.zeros((400, 600, 3), dtype=np.uint8)
        for i in range(400):
            for j in range(600):
                img_array[i, j] = [
                    int(255 * (i / 400)),
                    int(255 * (j / 600)),
                    150
                ]
        image = Image.fromarray(img_array)

    processed = image.copy()

    # Apply effect
    if effect == "Blur":
        processed = processed.filter(ImageFilter.BLUR)
    elif effect == "Sharpen":
        processed = processed.filter(ImageFilter.SHARPEN)
    elif effect == "Edge Enhance":
        processed = processed.filter(ImageFilter.EDGE_ENHANCE)
    elif effect == "Emboss":
        processed = processed.filter(ImageFilter.EMBOSS)
    elif effect == "Grayscale":
        processed = processed.convert('L').convert('RGB')

    # Apply brightness
    enhancer = ImageEnhance.Brightness(processed)
    processed = enhancer.enhance(brightness / 100)

    # Apply rotation
    if rotation != 0:
        processed = processed.rotate(rotation, expand=True, fillcolor='white')

    # Generate processing info
    info = f"""
    🎨 **Processing Details**

    - **Original Size**: {image.size[0]} x {image.size[1]} pixels
    - **Effect Applied**: {effect}
    - **Brightness**: {brightness}%
    - **Rotation**: {rotation}°
    - **Processed Size**: {processed.size[0]} x {processed.size[1]} pixels
    - **Mode**: {processed.mode}
    """

    return processed, info


# ============================================================================
# Demo 4: Calculator & Converter
# ============================================================================

@fastdash(
    title="🔢 Smart Calculator & Unit Converter",
    subheader="Perform calculations and unit conversions in real-time",
    theme="MINTY"
)
def calculator_converter(
    operation: str = ["Add", "Subtract", "Multiply", "Divide", "Power", "Convert Temperature", "Convert Length"],
    value1: float = 10.0,
    value2: float = 5.0,
    from_unit: str = ["Celsius", "Fahrenheit", "Kelvin", "Meters", "Feet", "Miles", "Kilometers"],
    to_unit: str = ["Celsius", "Fahrenheit", "Kelvin", "Meters", "Feet", "Miles", "Kilometers"]
) -> (str, go.Figure):
    """
    Multi-Purpose Calculator and Unit Converter

    Perform basic arithmetic operations or convert between different units.
    Includes temperature and length conversions.
    """

    result_text = ""

    # Basic calculations
    if operation == "Add":
        result = value1 + value2
        result_text = f"{value1} + {value2} = **{result}**"
    elif operation == "Subtract":
        result = value1 - value2
        result_text = f"{value1} - {value2} = **{result}**"
    elif operation == "Multiply":
        result = value1 * value2
        result_text = f"{value1} × {value2} = **{result}**"
    elif operation == "Divide":
        result = value1 / value2 if value2 != 0 else "Error: Division by zero"
        result_text = f"{value1} ÷ {value2} = **{result}**" if value2 != 0 else str(result)
    elif operation == "Power":
        result = value1 ** value2
        result_text = f"{value1}^{value2} = **{result}**"

    # Temperature conversion
    elif operation == "Convert Temperature":
        # Convert to Celsius first
        if from_unit == "Fahrenheit":
            celsius = (value1 - 32) * 5/9
        elif from_unit == "Kelvin":
            celsius = value1 - 273.15
        else:
            celsius = value1

        # Convert from Celsius to target
        if to_unit == "Fahrenheit":
            result = celsius * 9/5 + 32
        elif to_unit == "Kelvin":
            result = celsius + 273.15
        else:
            result = celsius

        result_text = f"{value1}° {from_unit} = **{result:.2f}°** {to_unit}"

    # Length conversion
    elif operation == "Convert Length":
        # Convert to meters first
        to_meters = {
            "Meters": 1,
            "Feet": 0.3048,
            "Miles": 1609.34,
            "Kilometers": 1000
        }

        meters = value1 * to_meters.get(from_unit, 1)
        result = meters / to_meters.get(to_unit, 1)
        result_text = f"{value1} {from_unit} = **{result:.4f}** {to_unit}"

    # Create a visual representation
    if operation in ["Add", "Subtract", "Multiply", "Divide", "Power"]:
        # Show calculation history with a bar chart
        fig = go.Figure(data=[
            go.Bar(name='Value 1', x=['Input'], y=[value1], marker_color='lightblue'),
            go.Bar(name='Value 2', x=['Input'], y=[value2], marker_color='lightcoral'),
            go.Bar(name='Result', x=['Output'], y=[result if isinstance(result, (int, float)) else 0], marker_color='lightgreen')
        ])
        fig.update_layout(title=f"Visual: {operation}", template="plotly_white", height=400)
    else:
        # Show conversion with a line plot
        fig = go.Figure()
        fig.add_trace(go.Indicator(
            mode="number+delta",
            value=result if isinstance(result, (int, float)) else 0,
            title={'text': f"{from_unit} → {to_unit}"},
            delta={'reference': value1}
        ))
        fig.update_layout(height=400)

    full_output = f"""
    🔢 **Calculation Result**

    {result_text}

    **Operation**: {operation}
    **Timestamp**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
    """

    return full_output, fig


# Main entry point
if __name__ == "__main__":
    # You can run any of the demos above
    # Uncomment the one you want to run:

    data_visualizer()  # Demo 1: Main dashboard
    # text_analyzer()    # Demo 2: Text tools
    # image_processor()  # Demo 3: Image effects
    # calculator_converter()  # Demo 4: Calculator
