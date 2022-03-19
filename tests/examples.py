from fast_dash import FastDash, Fastify
from fast_dash.Components import Text, Image, Upload, Slider, html, dcc


def example_1_simple_text_to_text():
    "Fast Dash example 1. Simple text to text Fast Dash app"
    ## Define callback functions
    def simple_text_to_text_function(input_text):
        return input_text

    app = FastDash(
        callback_fn=simple_text_to_text_function,
        inputs=Text,
        outputs=Text,
        title="Fast Dash example 1",
    )

    return app


def example_2_text_with_slider():
    "Fast Dash example 2"

    # Step 1: Define your model inference
    def text_to_text_function(input_text, slider_value):
        processed_text = f'{input_text}. Slider value is {slider_value}.'
        return processed_text

    # Step 2: Specify the input and output components
    app = FastDash(callback_fn=text_to_text_function, 
                    inputs=[Text, Slider], 
                    outputs=Text,
                    title='Fast Dash example 2')

    return app


def example_3_image_to_image():
    "Fast Dash example 3"

    # Step 1: Define your model inference
    def callback_fn(image):
        return image

    # Step 2: Specify the input and output components
    app = FastDash(callback_fn=callback_fn, 
                    inputs=Upload, 
                    outputs=Image,
                    title='Fast Dash example 3')

    return app


def example_4_image_slider_to_image_text():
    "Fast Dash example 4. Input is Upload (with ack) and slider. Output is Image and Text."

    def callback_fn(input_text, slider_value):
        return input_text, f"Slider value is {slider_value}"

    ack_image = Fastify(html.Img, 'src', width='100%')
    fast_upload = Fastify(dcc.Upload, 'contents', ack=ack_image, children=["Click to upload"], style={'borderStyle': 'dashed', 'padding-bottom':'20px'})

    app = FastDash(callback_fn=callback_fn, 
                        inputs=[fast_upload, Slider],
                        outputs=[Image, Text], 
                        title='Fast Dash example 4',
                        theme='SKETCHY')

    return app