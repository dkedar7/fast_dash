# Fast Components

Fast components are the UI components that represent the input and outputs elements in a Fast Dash app. In fact, they are Dash components modified by adding a new `component_property` attribute, in addition to a few other optional properties. Fast Dash provides a `Fastify` function to transform Dash components into Fast components.

Fast Dash borrows the concept of `component_property` from Dash. `component_property` is the answer to the question - __"Which property of a component should be assigned the value returned by the callback function?"__

For example, if the first argument of a Fast Dash callback function is a `str`, we must represent this input using a component that allows users to enter text. Say we decide to use the `dbc.Input()` Dash component. On referring to the documentation of the component [here](https://dash-bootstrap-components.opensource.faculty.ai/docs/components/input/), you'll realize that we must update the `value` property of `dbc.Input()` for it to work as expected. And therefore, when defining a Fast component for this input we would use `component_property="value"`.

We use this design and the fact that Fast Dash allows using Fast components as type hints, in addition of standard Python data types, to write a simple app that takes text entered by users as the first input.

```py hl_lines="3 6"
from fast_dash import Fastify, dbc

text_input_component = Fastify(component=dbc.Input(), component_property="value")

@fastdash
def your_function(input_text: text_input_component, ...):
    ...
```

!!! note

    Note that Fast Dash offers prebuilt Fast Components for common use cases. Some of them are <br>
    - `Text`: To allow entering input text<br>
    - `Slider`: For integer inputs<br>
    - `Upload`: Used to upload documents<br>
    - `UploadImage`: Special case of `Upload` used to upload images<br>
    - `Image`: Used to display image variables returned by callback functions.<br>
    - `Graph`: Display Plotly graphs<br>

    These can be easily imported into your script like this:

    ```py
    from fast_dash import Text, Slider, Upload, UploadImage, Image, Graph
    ```

!!! note "Dash components vs Fast components"

    Dash components are interactive UI components that you can use to create web applications with Dash. Dash ships with supercharged core components (`dash.dcc`), and standard HTML components (`dash.html`) suitable for almost any task and data type.

    Fast components are Dash components with some additional attributes to make them suitable for use by Fast Dash.

    If you have used Dash, you will know that it requires us to specify a `component_property` argument to Dash's `Input` and `Output` methods when defining our callback functions (during runtime). In other words, we can develop Dash UI before writing our callback functions.

    On the contrary, Fast Dash **infers** components (when not specified) by studying the underlying callback function, particularly its type hints and default values.

## Can Dash components be used as Fast Components?

**Yes!**

However, Dash components have to be converted to Fast components before Fast Dash uses them. In most cases, Fast Dash performs that conversion automatically. But in the other cases, we can easily use the `Fastify` utility function to do that conversion ourselves.

Here's a list of all Dash components that Fast Dash natively converts to Fast components without worrying the user.


## How to transform Dash components into Fast components

If the Dash components you want to use isn't in the list of components you want to use with Fast Dash or if you want to update a different `component_property` of the component, then the `Fastify` function comes to your rescue.

Use this syntax to do the conversion:

```py
...
from fastdash import Fastify

fast_component = Fastify(component=dash_component, component_property=...)
```

For example, Fast Dash doesn't natively support automatic conversion of [Dash bio components](https://dash.plotly.com/dash-bio/molecule2dviewer) to Fast components. But, `Fastify` can convert any Dash component to a Fast component. Say, we wanted to use `dash.bio.Molecule2dViewer` to view a molecule:

```py
from fast_dash import fastdash, Fastify
from dashbio import Molecule2dViewer

molecule_fast_component = Fastify(component=Molecule2dViewer(), 
                                    component_property="modelData")

def view_molecule(...) -> molecule_fast_component:
    ...
```