from fast_dash import FastDash, Fastify
from fast_dash.Components import Text, Slider


def example_1_simple_text_to_text():
    "Simple text to etxt Fast Dash app"
    ## Define callback functions
    def simple_text_to_text_function(input_text):
        return input_text

    app = FastDash(
        callback_fn=simple_text_to_text_function,
        inputs=Text,
        outputs=Text,
        title="App title",
    )

    return app


def example_2_text_with_slider():
    "Fast Dash example 3"

    # Step 1: Define your model inference
    def text_to_text_function(input_text, slider_value):
        processed_text = f'{input_text}. Slider value is {slider_value}.'
        return processed_text

    # Step 2: Specify the input and output components
    app = FastDash(callback_fn=text_to_text_function, 
                    inputs=[Text, Slider], 
                    outputs=Text,
                    title='App title')

    return app