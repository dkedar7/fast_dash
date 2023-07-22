#!/usr/bin/env python
"""Tests for `fast_dash` package."""
# pylint: disable=redefined-outer-name

from fast_dash import FastDash, dcc, dbc, html
from fast_dash.Components import Text, Slider, UploadImage
from fast_dash.utils import _pil_to_b64

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
    assert app.inputs_with_ids[0].__doc__ == Text.__doc__

    # Input type is Slider
    app = FastDash(callback_fn=simple_number_to_number, inputs=Slider)
    assert app.inputs_with_ids[0].__doc__ == Slider.__doc__

    # Input type is Image
    app = FastDash(callback_fn=simple_image_to_image, inputs=UploadImage)
    assert app.inputs_with_ids[0].__doc__ == UploadImage.__doc__


def test_fdco002_hint_is_not_of_type_type(dash_duo):
    "Input is not of type `type`"

    # Hint is text
    def simple_text(text: "Fast Dash"):
        return text

    app = FastDash(callback_fn=simple_text)
    input_component = app.inputs_with_ids[0]
    assert input_component.__doc__ == dbc.Input().__doc__ and not hasattr(
        input_component, "type"
    )

    # Hint is integer
    def simple_integer(integer: 5):
        return integer

    app = FastDash(callback_fn=simple_integer)
    input_component = app.inputs_with_ids[0]
    assert (
        input_component.__doc__ == dbc.Input().__doc__
        and input_component.type == "number"
    )


def test_fdco003_input_is_image(dash_duo):
    "When hint and default values are independently PIL images"

    # Input hint is PIL image
    import PIL
    from PIL import ImageFile

    def simple_image(image: PIL.ImageFile.ImageFile):
        return image

    app = FastDash(callback_fn=simple_image)
    input_component = app.inputs_with_ids[0]
    assert input_component.__doc__ == UploadImage.__doc__

    # Defualt value is image
    from PIL import Image
    import requests
    from io import BytesIO

    url = "https://raw.githubusercontent.com/dkedar7/fast_dash/docs/docs/assets/favicon.jpg"
    response = requests.get(url)
    img = Image.open(BytesIO(response.content))

    def simple_image(image=img):
        return image

    app = FastDash(callback_fn=simple_image)
    input_component = app.inputs_with_ids[0]
    assert (
        input_component.__doc__ == UploadImage.__doc__
        and input_component.ack.__doc__ == html.Img.__doc__
    )


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
    )

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
    )

    # 3. Default is sequence
    def simple_text(text: str = ["Some text", 2.2, "45.23"]):
        return text

    app = FastDash(callback_fn=simple_text)
    input_component = app.inputs_with_ids[0]
    assert (
        input_component.__doc__ == dcc.Dropdown().__doc__
        and hasattr(input_component, "options")
        and input_component.options == ["Some text", 2.2, "45.23"]
    )

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
    )

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
    )

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
    )

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
    )


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
    )

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
    )

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
    )

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
    )


def test_fdco006_input_hint_is_sequence(dash_duo):
    "Try different default types when the input hint is a sequence"

    # 1. Default is text
    def simple_list(l_: list = "This, is,a,list, 2.2"):
        return l_

    app = FastDash(callback_fn=simple_list)
    input_component = app.inputs_with_ids[0]
    assert (
        input_component.__doc__ == dbc.Input().__doc__
        and not hasattr(input_component, "type")
        and hasattr(input_component, "value")
        and input_component.value == ["This", "is", "a", "list", "2.2"]
    )

    # 2. Default is a list (sequence)
    def simple_list(l_: list = ["This", "is", "a", "list", "2.2"]):
        return l_

    app = FastDash(callback_fn=simple_list)
    input_component = app.inputs_with_ids[0]
    assert (
        input_component.__doc__ == dcc.Dropdown().__doc__
        and not hasattr(input_component, "type")
        and hasattr(input_component, "options")
        and input_component.options == ["This", "is", "a", "list", "2.2"]
        and hasattr(input_component, "component_property")
        and input_component.component_property == "value"
    )

    # 3. Default is a dictionary (sequence)
    sample_dictionary = {"This": "is", "a": "dictionary", 5: "Fast", "Dash": [1, 2, 3]}

    def simple_list(l_: list = sample_dictionary):
        return l_

    app = FastDash(callback_fn=simple_list)
    input_component = app.inputs_with_ids[0]
    assert (
        input_component.__doc__ == dcc.Dropdown().__doc__
        and not hasattr(input_component, "type")
        and hasattr(input_component, "options")
        and input_component.options == sample_dictionary
        and hasattr(input_component, "component_property")
        and input_component.component_property == "value"
    )

    # 4. No default value
    sample_dictionary = {"This": "is", "a": "dictionary", 5: "Fast", "Dash": [1, 2, 3]}

    def simple_list(l_: list = sample_dictionary):
        return l_

    app = FastDash(callback_fn=simple_list)
    input_component = app.inputs_with_ids[0]
    assert (
        input_component.__doc__ == dcc.Dropdown().__doc__
        and not hasattr(input_component, "type")
        and hasattr(input_component, "component_property")
        and input_component.component_property == "value"
    )


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
    )


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
    )

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
    )


def test_fdco009_input_hint_is_image(dash_duo):
    "When the input hint is image"

    # 1. Default value is PIL image
    import PIL
    from PIL import Image
    import requests
    from io import BytesIO

    url = "https://raw.githubusercontent.com/dkedar7/fast_dash/docs/docs/assets/favicon.jpg"
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
    )


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
    )


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
    )

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
    )


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
    )

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
    )

    # 3a. Default value is a sequence (list)
    def simple_list(l_=["These", "are", 5, "options", "to select"]):
        return l_

    app = FastDash(callback_fn=simple_list)
    input_component = app.inputs_with_ids[0]

    assert (
        input_component.__doc__ == dcc.Dropdown().__doc__
        and hasattr(input_component, "options")
        and input_component.options == ["These", "are", 5, "options", "to select"]
    )

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
    )

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
    )

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
    )

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
    )

    # 7. Default value is timestamp (current treated as date)
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
    )

    # 8. Unsupported default value type
    def simple_unsupported(inp_=time.localtime()):
        return inp_

    app = FastDash(callback_fn=simple_unsupported)
    input_component = app.inputs_with_ids[0]

    assert input_component.__doc__ == dbc.Input().__doc__ and not hasattr(
        input_component, "type"
    )

    # 9. Default input type is `None`
    def simple_unsupported(inp_=None):
        return inp_

    app = FastDash(callback_fn=simple_unsupported)
    input_component = app.inputs_with_ids[0]

    assert input_component.__doc__ == dbc.Input().__doc__ and not hasattr(
        input_component, "type"
    )


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
    )


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
    )

    # 2. Output is an image object
    from PIL import Image
    import requests
    from io import BytesIO

    url = "https://raw.githubusercontent.com/dkedar7/fast_dash/docs/docs/assets/favicon.jpg"
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
    )

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
    )
