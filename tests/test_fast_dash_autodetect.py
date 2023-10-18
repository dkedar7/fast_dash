#!/usr/bin/env python
"""Tests for `fast_dash` package."""
# pylint: disable=redefined-outer-name

from fast_dash import FastDash, dcc, dbc, dmc, html, Chat
from fast_dash.Components import Text, Slider, UploadImage
from fast_dash.utils import _pil_to_b64, Fastify

from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

import time
import datetime


########### Define callback functions ###########
def simple_text_to_text_function(input_text: Text):
    "Converts text to text"
    return input_text


def simple_number_to_number(input_: Slider):
    return input_

def simple_image_to_image(input_: UploadImage):
    return UploadImage


def simple_text_to_multiple_text_function(input_text):
    return input_text, input_text


############## Write test cases ################
def test_fdco001_input_is_fc(dash_duo):
    "When the input is a FastComponent"

    # Input type is Text
    app = FastDash(callback_fn=simple_text_to_text_function)
    assert app.inputs_with_ids[0].__doc__ == Text.__doc__, "Input type is Text failed"

    # Input type is Slider
    app = FastDash(callback_fn=simple_number_to_number, inputs=Slider)
    assert app.inputs_with_ids[0].__doc__ == Slider.__doc__, "Input type is Slider failed"

    # Input type is Image
    app = FastDash(callback_fn=simple_image_to_image, inputs=UploadImage)
    assert app.inputs_with_ids[0].__doc__ == UploadImage.__doc__, "Input type is Image failed"


def test_fdco002_hint_is_not_of_type_type(dash_duo):
    "Input is not of type `type`"

    # Hint is text
    def simple_text(text: "Fast Dash"):
        return text

    app = FastDash(callback_fn=simple_text)
    input_component = app.inputs_with_ids[0]
    assert input_component.__doc__ == dmc.Textarea().__doc__ and not hasattr(
        input_component, "type"
    ), "Hint is text failed"

    # Hint is integer
    def simple_integer(integer: 5):
        return integer

    app = FastDash(callback_fn=simple_integer)
    input_component = app.inputs_with_ids[0]
    assert (
        input_component.__doc__ == dbc.Input().__doc__
        and input_component.type == "number"
    ), "Hint is integer failed"


def test_fdco003_input_is_image(dash_duo):
    "When hint and default values are independently PIL images"

    # Input hint is PIL image
    import PIL
    from PIL import ImageFile

    def simple_image(image: PIL.ImageFile.ImageFile):
        return image

    app = FastDash(callback_fn=simple_image)
    input_component = app.inputs_with_ids[0]
    assert input_component.__doc__ == UploadImage.__doc__, "Hint is PIL image failed"

    # Defualt value is image
    from PIL import Image
    import requests
    from io import BytesIO

    url = "https://storage.googleapis.com/fast_dash/0.2.7/Mosaic%20examples/ex1.png"
    response = requests.get(url)
    img = Image.open(BytesIO(response.content))

    def simple_image(image=img):
        return image

    app = FastDash(callback_fn=simple_image)
    input_component = app.inputs_with_ids[0]
    assert (
        input_component.__doc__ == UploadImage.__doc__
        and input_component.ack.__doc__ == html.Img.__doc__
    ), "Defualt value is image failed"


def test_fdco004_input_hint_is_text(dash_duo):
    "Try different default types when the input hint is text"

    # 1. Default is text
    def simple_text(text: str = "Default text"):
        return text

    app = FastDash(callback_fn=simple_text)
    input_component = app.inputs_with_ids[0]
    assert (
        input_component.__doc__ == Text.__doc__
        and hasattr(input_component, "value")
        and input_component.value == "Default text"
    ), "Default text failed"

    # 2. Default is numeric
    def simple_text(text: str = 2.2):
        return text

    app = FastDash(callback_fn=simple_text)
    input_component = app.inputs_with_ids[0]
    assert (
        input_component.__doc__ == dbc.Input().__doc__
        and hasattr(input_component, "type")
        and input_component.type == "number"
        and hasattr(input_component, "value")
        and input_component.value == 2.2
    ), "Default number failed"

    # 3. Default is sequence
    def simple_text(text: str = ["Some text", 2.2, "45.23"]):
        return text

    app = FastDash(callback_fn=simple_text)
    input_component = app.inputs_with_ids[0]
    assert (
        input_component.__doc__ == dcc.Dropdown().__doc__
        and hasattr(input_component, "options")
        and input_component.options == ["Some text", 2.2, "45.23"]
    ), "Default sequence failed"

    # 4. Default is dictionary
    def simple_text(
        text: str = {"This": "is", "a": "dictionary", 5: "Fast", "Dash": [1, 2, 3]}
    ):
        return text

    app = FastDash(callback_fn=simple_text)
    input_component = app.inputs_with_ids[0]
    assert (
        input_component.__doc__ == dbc.Input().__doc__
        and not hasattr(input_component, "type")
        and hasattr(input_component, "value")
        and input_component.value
        == str({"This": "is", "a": "dictionary", 5: "Fast", "Dash": [1, 2, 3]})
    ), "Default dictionary failed"

    # 5. Default is boolean
    def simple_text(text: str = True):
        return text

    app = FastDash(callback_fn=simple_text)
    input_component = app.inputs_with_ids[0]
    assert (
        input_component.__doc__ == dbc.Input().__doc__
        and not hasattr(input_component, "type")
        and hasattr(input_component, "value")
        and input_component.value == str(True)
    ), "Default boolean failed"

    # 5. Default is date
    def simple_text(text: str = datetime.date(2022, 8, 11)):
        return text

    app = FastDash(callback_fn=simple_text)
    input_component = app.inputs_with_ids[0]
    assert (
        input_component.__doc__ == dbc.Input().__doc__
        and not hasattr(input_component, "type")
        and hasattr(input_component, "value")
        and input_component.value == str(datetime.date(2022, 8, 11))
    ), "Default date failed"

    # 6. Default is datetime
    def simple_text(text: str = datetime.datetime(2022, 8, 11, 12, 44, 56)):
        return text

    app = FastDash(callback_fn=simple_text)
    input_component = app.inputs_with_ids[0]
    assert (
        input_component.__doc__ == dbc.Input().__doc__
        and not hasattr(input_component, "type")
        and hasattr(input_component, "value")
        and input_component.value == str(datetime.datetime(2022, 8, 11, 12, 44, 56))
    ), "Default datetime failed"


def test_fdco005_input_hint_is_numeric(dash_duo):
    "Try different default types when the input hint is numeric"

    # 1. Default is text
    def simple_num(num: float = "2.2"):
        return num

    app = FastDash(callback_fn=simple_num)
    input_component = app.inputs_with_ids[0]
    assert (
        input_component.__doc__ == dbc.Input().__doc__
        and hasattr(input_component, "type")
        and input_component.type == "number"
        and hasattr(input_component, "value")
        and input_component.value == 2.2
    ), "Default text failed"

    # 2. Default is numeric
    def simple_num(num: float = 2.2):
        return num

    app = FastDash(callback_fn=simple_num)
    input_component = app.inputs_with_ids[0]
    assert (
        input_component.__doc__ == dbc.Input().__doc__
        and hasattr(input_component, "type")
        and input_component.type == "number"
        and hasattr(input_component, "value")
        and input_component.value == 2.2
    ), "Default number failed"

    # 3a. Default value is of type range
    def simple_num(num: float = range(1, 10, 2)):
        return num

    app = FastDash(callback_fn=simple_num)
    input_component = app.inputs_with_ids[0]
    assert (
        input_component.__doc__ == dcc.Slider().__doc__
        and hasattr(input_component, "min")
        and input_component.min == 1
        and hasattr(input_component, "max")
        and input_component.max == 10
        and hasattr(input_component, "step")
        and input_component.step == 2
    ), "Default range failed"

    # 3b. Default value is other sequence (list)
    def simple_num(num: float = [0, 2, 3, 4, 5, 6, 7, 80]):
        return num

    app = FastDash(callback_fn=simple_num)
    input_component = app.inputs_with_ids[0]
    assert (
        input_component.__doc__ == dcc.Slider().__doc__
        and hasattr(input_component, "min")
        and input_component.min == 0
        and hasattr(input_component, "max")
        and input_component.max == 80
        and hasattr(input_component, "step")
        and input_component.step == 10
    ), "Default other sequence failed"


def test_fdco006_input_hint_is_sequence(dash_duo):
    "Try different default types when the input hint is a sequence"

    # 1. Default is text
    def simple_list(l_: list = "This, is,a,list, 2.2"):
        return l_

    app = FastDash(callback_fn=simple_list)
    input_component = app.inputs_with_ids[0]
    assert (
        input_component.__doc__ == dmc.MultiSelect().__doc__
        and not hasattr(input_component, "type")
        and hasattr(input_component, "value")
        and input_component.value == ["This, is,a,list, 2.2"]
    ), "Default text failed"

    # 2. Default is a list (sequence)
    def simple_list(l_: list = ["This", "is", "a", "list", "2.2"]):
        return l_

    app = FastDash(callback_fn=simple_list)
    input_component = app.inputs_with_ids[0]
    assert (
        input_component.__doc__ == dmc.MultiSelect().__doc__
        and not hasattr(input_component, "type")
        and hasattr(input_component, "data")
        and input_component.data == ["This", "is", "a", "list", "2.2"]
        and hasattr(input_component, "component_property")
        and input_component.component_property == "value"
    ), "Default list failed"

    # 3. Default is a dictionary (sequence)
    sample_dictionary = {"This": "is", "a": "dictionary", 5: "Fast", "Dash": [1, 2, 3]}

    def simple_list(l_: list = sample_dictionary):
        return l_

    app = FastDash(callback_fn=simple_list)
    input_component = app.inputs_with_ids[0]
    assert (
        input_component.__doc__ == dmc.MultiSelect().__doc__
        and not hasattr(input_component, "type")
        and hasattr(input_component, "data")
        and input_component.data == sample_dictionary
        and hasattr(input_component, "component_property")
        and input_component.component_property == "value"
    ), "Default dictionary failed"

    # 4. No default value
    def simple_list(l_: list):
        return l_

    app = FastDash(callback_fn=simple_list)
    input_component = app.inputs_with_ids[0]
    assert (
        input_component.__doc__ == dmc.MultiSelect().__doc__
        and not hasattr(input_component, "type")
        and hasattr(input_component, "component_property")
        and input_component.component_property == "value"
    ), "No default failed"


def test_fdco007_input_hint_is_dictionary(dash_duo):
    "When the input hint is dictionary"

    # 1. Default is dictionary
    sample_dictionary = {"This": "is", "a": "dictionary", 5: "Fast", "Dash": [1, 2, 3]}

    def simple_dictionary(l_: dict = sample_dictionary):
        return l_

    app = FastDash(callback_fn=simple_dictionary)
    input_component = app.inputs_with_ids[0]
    assert (
        input_component.__doc__ == dcc.Dropdown().__doc__
        and not hasattr(input_component, "type")
        and hasattr(input_component, "options")
        and input_component.options == sample_dictionary
        and hasattr(input_component, "component_property")
        and input_component.component_property == "value"
    ), "Default dictionary failed"


def test_fdco008_input_hint_is_boolean(dash_duo):
    "When the input hint is bool"

    # 1. Default is True
    def simple_bool(l_: bool = True):
        return l_

    app = FastDash(callback_fn=simple_bool)
    input_component = app.inputs_with_ids[0]
    assert (
        input_component.__doc__ == dbc.Checkbox().__doc__
        and hasattr(input_component, "value")
        and input_component.value is True
        and hasattr(input_component, "component_property")
        and input_component.component_property == "value"
    ), "Default = True failed"

    # No default value (False by default)
    def simple_bool(l_: bool):
        return l_

    app = FastDash(callback_fn=simple_bool)
    input_component = app.inputs_with_ids[0]
    assert (
        input_component.__doc__ == dbc.Checkbox().__doc__
        and not hasattr(input_component, "value")
        and hasattr(input_component, "component_property")
        and input_component.component_property == "value"
    ), "Default = False failed"


def test_fdco009_input_hint_is_image(dash_duo):
    "When the input hint is image"

    # 1. Default value is PIL image
    import PIL
    from PIL import Image
    import requests
    from io import BytesIO

    url = "https://storage.googleapis.com/fast_dash/0.2.7/Mosaic%20examples/ex1.png"
    response = requests.get(url)
    img = Image.open(BytesIO(response.content))

    def simple_img(img_: PIL.ImageFile.ImageFile = img):
        return img_

    app = FastDash(callback_fn=simple_img)
    dash_duo.start_server(app.app)
    dash_duo.wait_for_text_to_equal("#title8888928", "Simple Img", timeout=4)
    time.sleep(4)

    input_component = app.inputs_with_ids[0]
    assert (
        input_component.__doc__ == UploadImage.__doc__
        and hasattr(input_component, "component_property")
        and input_component.component_property == "contents"
        and hasattr(input_component, "ack")
        and input_component.ack.__doc__ == html.Img.__doc__
        and dash_duo.find_element("#img__ack").get_attribute("src") == _pil_to_b64(img)
    ), "Default image failed"


def test_fdco010_input_hint_is_image_no_default(dash_duo):
    "Hint is of type image and no defautl value"

    # 1. No default value
    import PIL

    def simple_img(img_: PIL.ImageFile.ImageFile):
        return img_

    app = FastDash(callback_fn=simple_img)
    dash_duo.start_server(app.app)
    dash_duo.wait_for_text_to_equal("#title8888928", "Simple Img", timeout=4)
    time.sleep(4)

    input_component = app.inputs_with_ids[0]
    assert (
        input_component.__doc__ == UploadImage.__doc__
        and hasattr(input_component, "component_property")
        and input_component.component_property == "contents"
        and hasattr(input_component, "ack")
        and input_component.ack.__doc__ == html.Img.__doc__
        and dash_duo.find_element("#img__ack").get_attribute("src") == None
    ), "No default value failed"


def test_fdco011_input_hint_is_date(dash_duo):
    "Hint is of type date"

    # 1 Default value is date
    def simple_date(date: datetime.date = datetime.date(2022, 5, 4)):
        return date

    app = FastDash(callback_fn=simple_date)
    input_component = app.inputs_with_ids[0]

    assert (
        input_component.__doc__ == dcc.DatePickerSingle.__doc__
        and hasattr(input_component, "component_property")
        and input_component.component_property == "date"
        and hasattr(input_component, "date")
        and input_component.date == datetime.date(2022, 5, 4)
    ), "Default date failed"

    # 2. No default value
    def simple_date(date: datetime.date):
        return date

    app = FastDash(callback_fn=simple_date)
    input_component = app.inputs_with_ids[0]

    assert (
        input_component.__doc__ == dcc.DatePickerSingle.__doc__
        and hasattr(input_component, "component_property")
        and input_component.component_property == "date"
        and hasattr(input_component, "date")
        and input_component.date == datetime.date.today()
    ), "No default value failed"


def test_fdco012_input_hint_is_unknown(dash_duo):
    "When the input hint is unknown or unsupported"

    # 1. Default value is text
    def simple_text(text="Some text"):
        return text

    app = FastDash(callback_fn=simple_text)
    input_component = app.inputs_with_ids[0]

    assert (
        input_component.__doc__ == dbc.Input().__doc__
        and not hasattr(input_component, "type")
        and hasattr(input_component, "value")
        and input_component.value == "Some text"
    ), "Default text failed"

    # 2. Default value is a number
    def simple_num(text=137.2736):
        return text

    app = FastDash(callback_fn=simple_num)
    input_component = app.inputs_with_ids[0]

    assert (
        input_component.__doc__ == dbc.Input().__doc__
        and hasattr(input_component, "type")
        and input_component.type == "number"
        and hasattr(input_component, "value")
        and input_component.value == 137.2736
    ), "Default number failed"

    # 3a. Default value is a sequence (list)
    def simple_list(l_=["These", "are", 5, "options", "to select"]):
        return l_

    app = FastDash(callback_fn=simple_list)
    input_component = app.inputs_with_ids[0]

    assert (
        input_component.__doc__ == dcc.Dropdown().__doc__
        and hasattr(input_component, "options")
        and input_component.options == ["These", "are", 5, "options", "to select"]
    ), "Default list failed"

    # 3b. Default value is range
    def simple_range(l_=range(1, 1000, 5)):
        return l_

    app = FastDash(callback_fn=simple_range)
    input_component = app.inputs_with_ids[0]

    assert (
        input_component.__doc__ == dcc.Slider().__doc__
        and hasattr(input_component, "min")
        and input_component.min == 1
        and hasattr(input_component, "max")
        and input_component.max == 1000
        and hasattr(input_component, "step")
        and input_component.step == 5
    ), "Default range failed"

    # 4. Default value is a dictionary
    def simple_dict(l_={"This": "is", "a": "dictionary", 5: "Fast", "Dash": [1, 2, 3]}):
        return l_

    app = FastDash(callback_fn=simple_dict)
    input_component = app.inputs_with_ids[0]

    assert (
        input_component.__doc__ == dcc.Dropdown().__doc__
        and hasattr(input_component, "options")
        and input_component.options
        == {"This": "is", "a": "dictionary", 5: "Fast", "Dash": [1, 2, 3]}
    ), "Default dictionary failed"

    # 5. Default value is boolean
    def simple_bool(l_=True):
        return l_

    app = FastDash(callback_fn=simple_bool)
    input_component = app.inputs_with_ids[0]

    assert (
        input_component.__doc__ == dbc.Checkbox().__doc__
        and hasattr(input_component, "component_property")
        and input_component.component_property == "value"
        and hasattr(input_component, "value")
        and input_component.value is True
    ), "Default boolean failed"

    # 6. Default value is date
    def simple_date(l_=datetime.date(2022, 12, 25)):
        return l_

    app = FastDash(callback_fn=simple_date)
    input_component = app.inputs_with_ids[0]

    assert (
        input_component.__doc__ == dcc.DatePickerSingle.__doc__
        and hasattr(input_component, "component_property")
        and input_component.component_property == "date"
        and hasattr(input_component, "date")
        and input_component.date == datetime.date(2022, 12, 25)
    ), "Default date failed"

    # 7. Default value is timestamp (currently treated as date)
    def simple_datetime(l_=datetime.datetime(2022, 12, 25, 14, 55, 35)):
        return l_

    app = FastDash(callback_fn=simple_datetime)
    input_component = app.inputs_with_ids[0]

    assert (
        input_component.__doc__ == dcc.DatePickerSingle.__doc__
        and hasattr(input_component, "component_property")
        and input_component.component_property == "date"
        and hasattr(input_component, "date")
        and input_component.date == datetime.date(2022, 12, 25)
    ), "Default timestamp failed"

    # 8. Unsupported default value type
    def simple_unsupported(inp_=time.localtime()):
        return inp_

    app = FastDash(callback_fn=simple_unsupported)
    input_component = app.inputs_with_ids[0]

    assert input_component.__doc__ == dmc.Textarea().__doc__ and not hasattr(
        input_component, "type"
    ), "Default unsupported failed"

    # 9. Default input type is `None`
    def simple_unsupported(inp_=None):
        return inp_

    app = FastDash(callback_fn=simple_unsupported)
    input_component = app.inputs_with_ids[0]

    assert input_component.__doc__ == dmc.Textarea().__doc__ and not hasattr(
        input_component, "type"
    ), "Default None failed"


def test_fdco013_output_hint_is_fast_component(dash_duo):
    "When the output hint type is a Fast Component"

    def simple_number(num) -> Slider:
        return num

    app = FastDash(callback_fn=simple_number)
    output_component = app.outputs[0]

    assert (
        output_component.__doc__ == dcc.Slider().__doc__
        and hasattr(output_component, "min")
        and output_component.min == 0
        and hasattr(output_component, "max")
        and output_component.max == 20
        and hasattr(output_component, "step")
        and output_component.step == 1
    ), "Default FC failed"


def test_fdco014_output_hint_is_image(dash_duo):
    "When the output hint type is an image or type(image)"

    # 1. Output is subclass of PIL.ImageFile.ImageFile
    import PIL

    def simple_image(img) -> PIL.ImageFile.ImageFile:
        return img

    app = FastDash(callback_fn=simple_image)
    output_component = app.outputs[0]

    assert (
        output_component.__doc__ == html.Img.__doc__
        and hasattr(output_component, "component_property")
        and output_component.component_property == "src"
    ), "Default PIL.ImageFile.ImageFile failed"

    # 2. Output is an image object
    from PIL import Image
    import requests
    from io import BytesIO

    url = "https://storage.googleapis.com/fast_dash/0.2.7/Mosaic%20examples/ex1.png"
    response = requests.get(url)
    img = Image.open(BytesIO(response.content))

    def simple_image(img_) -> img:
        return img_

    app = FastDash(callback_fn=simple_image)
    output_component = app.outputs[0]

    assert (
        output_component.__doc__ == html.Img.__doc__
        and hasattr(output_component, "component_property")
        and output_component.component_property == "src"
    ), "Default image failed"

    # 3. Output is of type `type(image)`
    img_type = type(img)

    def simple_image(img_) -> img_type:
        return img_

    app = FastDash(callback_fn=simple_image)
    output_component = app.outputs[0]

    assert (
        output_component.__doc__ == html.Img.__doc__
        and hasattr(output_component, "component_property")
        and output_component.component_property == "src"
    ), "Default type(image) failed"


def test_fdco015_input_is_dash_component(dash_duo):
    "When the input hint type is a Dash component"

    # Component property is specified
    component = Fastify(dmc.Text(), "children")

    def simple_text_to_text(text: component):
        return "Some markdown text"

    app = FastDash(callback_fn=simple_text_to_text)
    input_component = app.inputs[0]

    assert (
        input_component.__doc__ == dmc.Text.__doc__
        and hasattr(input_component, "component_property")
        and input_component.component_property == "children"
    ), "Fast component failed"

    # Component property is not specified
    def simple_text_to_text(text: dmc.Text()):
        return "Some markdown text"

    app = FastDash(callback_fn=simple_text_to_text)
    input_component = app.inputs[0]

    assert (
        input_component.__doc__ == dmc.Text.__doc__
        and hasattr(input_component, "component_property")
        and input_component.component_property == "children"
    ), "Dash component failed"


def test_fdco016_output_is_dash_component(dash_duo):
    "When the output hint type is a Dash component"

    # Component property is specified
    component = Fastify(dcc.Markdown(), "children")

    def simple_text_to_text(text) -> component:
        return "Some markdown text"

    app = FastDash(callback_fn=simple_text_to_text)
    output_component = app.outputs[0]

    assert (
        output_component.__doc__ == dcc.Markdown.__doc__
        and hasattr(output_component, "component_property")
        and output_component.component_property == "children"
    ), "Fast component failed"

    # Component property is not specified
    def simple_text_to_text(text) -> dcc.Markdown():
        return "Some markdown text"

    app = FastDash(callback_fn=simple_text_to_text)
    output_component = app.outputs[0]

    assert (
        output_component.__doc__ == dcc.Markdown.__doc__
        and hasattr(output_component, "component_property")
        and output_component.component_property == "children"
    ), "Dash component failed"


def test_fdco017_output_is_chat(dash_duo):
    "When the output hint type is a Chat Fast component"

    def simple_chat(query: str) -> Chat:
        response = f"Response to {query}"
        chat = {"query": query, "response": response}
        
        return chat
    
    app = FastDash(callback_fn=simple_chat).app

    dash_duo.start_server(app)
    dash_duo.wait_for_text_to_equal("#title8888928", "Simple Chat", timeout=4)

    # Enter some text
    form_textfield = dash_duo.find_element("#query")
    form_textfield.send_keys("Why?")

    # Click submit
    dash_duo.multiple_click("#submit_inputs", 1)

    # Check if any child element has the text "Response to Why?"
    output_div = dash_duo.find_element("#output-1")

    wait = WebDriverWait(dash_duo.driver, timeout=4)
    wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "#output-1")))
    time.sleep(4)

    child_elements = output_div.find_elements(By.CSS_SELECTOR, "*")
    text_found = False

    for element in child_elements:
        if "Response to Why?" in element.text:
            text_found = True
            break

    assert text_found, "Response text not found in any child element of output-1"


def test_fdco018_output_is_pandas(dash_duo):
    "When the output hint type is a Chat Fast component"

    import pandas as pd
    def simple_table(dummy_input: int) -> pd.DataFrame:
        df = pd.DataFrame(data={"Col1": range(100), 
                                "Col2": [f"C{i}" for i in range(100)],
                                "Date": pd.date_range(start="2023-01-01", periods=100)})
        
        return df

    app = FastDash(callback_fn=simple_table).app

    dash_duo.start_server(app)
    dash_duo.wait_for_text_to_equal("#title8888928", "Simple Table", timeout=4)

    # Click submit
    dash_duo.multiple_click("#submit_inputs", 1)
    time.sleep(4)

    # Ensure the table is present
    table = dash_duo.find_element("#output-1")
    assert table is not None
    
    # Validate the data (example: check the first cell)
    first_cell = table.find_element_by_css_selector(".dash-cell div")
    assert first_cell.text == "0"  # Adjust according to expected content