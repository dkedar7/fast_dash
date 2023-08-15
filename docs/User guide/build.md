# 10 minutes to Fast Dash

This quick introduction to Fast Dash is geared mainly toward new users. If you've been here before, use the table of contents to jump to a specific section.

## Principles

!!! Abstract "Fast Dash's foundational principles"

    Fast Dash operates on two foundational principles:

    1. Every Python-based web application originates from a singular Python function.
    2. A comprehensively annotated Python function encapsulates all the information necessary to generate an interactive web application.

To obey these principles, Fast Dash reads everything about a Python function, like the function name, docstring, and input and output type hints, to automatically generate a layout and an interactive web application!

The callback function and Fast Dash app configurations together determine how the app is deployed and the level of user interaction. A well-annotated callback function almost always ensures minimal custom tweaking of app configurations.

Let's discuss ways to build Fast Dash apps and customize them.

## Building your Fast Dash app
There are two ways to build a Fast Dash app:

1. Decorating Python functions with the `@fastdash` decorator

``` py hl_lines="3"
from fast_dash import fastdash

@fastdash(...)
def your_function(...):
    ...
```
2. Instantiating an object of the `FastDash` class

``` py hl_lines="6 7"
from fast_dash import FastDash

def your_function(...):
    ...

app = FastDash(callback_fn=your_function, ...)
app.run()
```

Using the `@fastdash` decorator is the quickest way to deploy Fast Dash apps. On the other hand, the `FastDash` class gives us access to other Fast Dash internals and allows us to tweak them as we see fit.

Whereas the `@fastdash` decorator deploys our app when defining our functions (eagerly), the `FastDash` class objects are equivalent to Flask's server objects, allowing us to deploy our app later (lazily). `FastDash` objects must be explicitly told to `.run()` to deploy them. We'll understand these differences better throughout the remainder of this document.

!!! note
    Both the `@fastdash` decorator and the `FastDash` class objects are functionally equivalent. The `@fastdash` decorator is built on top of the `FastDash` class. That means any argument valid for `FastDash` object initialization can also be specified to `@fastdash`.

    Using decorators is a very convenient way to give additional abilities to a function, the callback function in our case. It also allows us to add various automations, like instant deployments!


Let's first understand how we can build Fast Dash apps using the `@fastdash` decorator and then extend these ideas to the `FastDash` class.

### 1. `@fastdash` decorator

#### What's a decorator?

In a nutshell, Python decorators are function wrappers that enrich the functionality of Python functions. [Here's](https://realpython.com/primer-on-python-decorators/) an in-depth write-up on Python decorators, what they are, and how to build them. All we need to know for now is that decorators are Python functions that wrap other functions to give them extra functionality.

The `@fastdash` decorator is also just a function (read more here about the implementation in the [Modules](../api.md) section) that takes the callback function as the first argument and designs a web app around it. But instead of explicitly specifying the callback function as the first argument, we use this syntax instead:

```py
@fastdash
def callback_function(...)
    ...
```

#### How to use `@fastdash`

After we have a Python function that runs without errors, there are only two things we need to do:

#### 1.1. Specify the input and output type hints
Fast Dash uses these type hints to determine which UI components to use. For example, an input with the type hint `int` will need an input that allows entering integers or a slider. Similarly, an image input will need a component to upload an image or take a photo.

!!! question "What are type hints?"
    First introduced in Python 3.5, __type hints__ are mainly meant to be used by IDEs and linters to raise data type mismatch warnings. They are not executed during runtime, and errors with type hinting don't affect the execution of the function. Read more about Python type hints [here](https://docs.python.org/3/library/typing.html).

    ```py
    def your_function(a: str, 
                      b: int, 
                      c: list) -> str:
        ...
    ```

    Fast Dash leverages this flexibility in defining type hints to allow using Dash components as hints. Read more on this in the documentation for [Fast Components](components.md).

Fast Dash understands two types of type hints—one, in-built Python data type classes (`str`, `int`, `float`, `list`, `dict`, etc.), and two, [Dash Components](components.md) directly.

In addition to type hints, the input arguments can also have default values. In the example below, the default value of string `a` is `Fast`, that of integer `b` is `5`, and `c` is a `list` with a default value of `[1, 2, 3]`. The function returns a single string value, as indicated by the return variable type hint (`-> str:`).

```py hl_lines="1 2 3"
def your_function(a: str = "Fast", 
                  b: int = 5, 
                  c: list = [1, 2, 3]) -> str:
    ...
```

Fast Dash determines the best components for each input using their hints and default values. Details about which combination of these values results in what components are in the [patterns documentation](patterns.md).

Dash components are also valid type hints for Fast Dash. Instead of depending on the hints and default values, using Dash components directly tells Fast Dash which components to use. In the example below, `UploadImage` and `Slider` are in-built Fast Component wrappers for [`dcc.Upload`](https://dash.plotly.com/dash-core-components/upload) and [`dcc.Slider`](https://dash.plotly.com/dash-core-components/slider) respectively. The function returns a text field, represented using the [`html.H1`](https://dash.plotly.com/dash-html-components/h1) component by default.

```py hl_lines="1 4 5"
from fast_dash import fastdash, dcc

@fastdash
def your_function(image: dcc.Upload(...), 
                  number: dcc.Slider(...)):
    ...
```

!!! question "What are Dash components?"
    Dash components are interactive UI components that you can use to create web applications with Dash. Dash ships with supercharged core components (`dash.dcc`), and standard HTML components (`dash.html`) suitable for almost any task and data type.

    In addition to these, there are many other community components, and those worth mentioning are:

    - [Dash boostrap components](https://dash-bootstrap-components.opensource.faculty.ai/docs/components/)
    - [Dash mantine components](https://www.dash-mantine-components.com/)

    [Here's](https://dash.plotly.com/dash-core-components) a list of many other Dash components. In fact, Dash also allows you to [design your own components](https://dash.plotly.com/plugins) using Javascript-based frameworks.

    !!! note "Which of these does Fast Dash support?"
        Short answer: **All of them!**

        Fast Dash converts a few Dash components to Fast components natively. But most have to be slightly modified before they can be used in a Fast Dash app.
        
        For example, Fast Dash doesn't natively support automatic conversion of [Dash bio components](https://dash.plotly.com/dash-bio/molecule2dviewer) to Fast components. However, Fast Dash offers a utility function, `Fastify` that can convert any Dash component to a Fast component. Say, we wanted to use `dash.bio.Molecule2dViewer` to view a molecule:

        ```py
        from fast_dash import fastdash, Fastify
        from dashbio import Molecule2dViewer

        molecule_fast_component = Fastify(component=Molecule2dViewer(), 
                                          component_property="modelData")

        def view_molecule(...) -> molecule_fast_component:
            ...
        ```

        Read more about `Fastify` [here](../../api/#fast_dash.Fastify).


#### 1.2. Modify default settings

Fast Dash allows you to customize your app by controlling various options like the theme of the app, social media branding links, and subheaders. Let's look at all these options in this section.

##### 1. Title

Fast Dash can read the name of our callback function and display it as the title at the top of the app. Function names resolve to titles the best if they are written in [snake case](https://en.wikipedia.org/wiki/Snake_case).

For example, `your_function` resolves to `Your Function` but `yourFunction` will resolve to `YourFunction`. For such cases, we can manually specify the title as an argument to `@fastdash`.

```py hl_lines="1"
@fastdash(title="Your Function")
def yourFunction(...):
    ...
```

##### 2. Subheader

The subheader shows up below the title at the top of the page in an italicized font. Fast Dash attempts to infer this from the function docstring. But we can also overwrite it with the `subheader` argument to `@fastdash`.

```py hl_lines="2 4"
@fastdash(title="Your Function", 
          subheader="Coolest Function Ever") # Either here
def yourFunction(...):
    "Coolest Function Ever" # or here
    ...
```

##### 3. Title image path

Fast Dash optionally displays an icon image below the title and subheader. The image path can be set with the argument `title_image_path`.

```py hl_lines="1"
@fastdash(title_image_path="https://tinyurl.com/5fw564ux")
def yourFunction(...):
    ...
```

##### 4. Social media URLs

We can also set social media URLs (Fast Dash supports GitHub, LinkedIn and Twitter URLs so far) in the navigation bar at the top by setting the arguments `github_url`, `linkedin_url`, and `twitter_url` respectively.

```py hl_lines="1 2 3"
@fastdash(github_url="github.com/dkedar7",
        linkedin_url="linkedin.com/in/dkedar7",
        twitter_url="twitter.com/dkedar7")
def yourFunction(...):
    ...
```

##### 5. Mosaic layout

When there are multiple outputs, we might want to control the layout of the output components. Inspired by Matplotlib's `subplot_mosaic`, Fast Dash allows using ASCII art arrays to control the arrangement of the output components on the screen.

More on using mosaic layout on the [common patterns page](../patterns).

##### 6. Navbar and footer visibility

We can hide the navbar and the footer by controlling the boolean `navbar` and `footer` arguments respectively. These are set to `True` by default.

```py hl_lines="1 2"
@fastdash(navbar=False,
        footer=False)
def yourFunction(...):
    ...
```

##### 7. Theme

The default theme that Fast Dash uses is called `JOURNAL`, but there are more themes that Fast Dash supports. See the complete list of supported themes at [bootswatch.com](https://bootswatch.com/).

```py hl_lines="1"
@fastdash(theme='JOURNAL')
def yourFunction(...):
    ...
```

##### 8. Update Live

By default, Fast Dash apps update lazily. That means once the user enters inputs, the outputs update only after they click `Submit`. But on setting the `update_live` argument to `True`, the `Submit` and `Reset` buttons disappear, and the outputs update instantaneously. This feature is also popularly known as hot reloading.

```py hl_lines="1"
@fastdash(update_live=True)
def yourFunction(...):
    ...
```

##### 9. Mode

`mode` is an interesting setting that decides how Fast Dash apps are deployed. There are currently four supported modes. The default mode is `None`, and the other possible `mode` options specified below require the [`jupyter-dash`](https://pypi.org/project/jupyter-dash/) library installed. Read more about the library [here](https://github.com/plotly/jupyter-dash).

`mode=None`

By default, `mode` is set to `None` which deploys the app at the chosen port (default port is 8080).

`mode="JupyterLab"`

When `mode` is `JupyterLab`, the app is deployed within Jupyter environments (like classic Notebook, JupyterLab, and VS Code notebooks). The app opens as a separate tab inside JupyterLab.

`mode="inline"`

With this `mode`, Fast Dash uses an IFrame to display the application inline in the notebook.

`mode="External"`

This behaves like the default mode with the only difference that the app runs outside your Jupyter notebook environment. Fast Dash display a link that where you can navigate to see how the deployment will look to end users after this application is depoyed to production.

```py hl_lines="1"
@fastdash(mode='jupyterlab')
def yourFunction(...):
    ...
```

##### 10. Minimal
Sometimes, we might want to see how our Python functions behave without worrying about the theme or the presence of the navbar or footer. If we set `minimal` to True, Fast Dash only displays the input and output components and hides the rest.

```py hl_lines="1"
@fastdash(minimal=True)
def yourFunction(...):
    ...
```

##### 11. Disable logs
Under the hood, setting `disable_logs` to `True` turns off the messy log output that sometimes follows a successful Fast Dash deployment. This feature comes in handy when we are deploying apps inside Jupyter environments. On the flip side, we lose a lot of useful debugging information.

```py hl_lines="1"
@fastdash(disable_logs=True)
def yourFunction(...):
    ...
```

<!-- disable_logs -->

<!-- All definitions and abbreviations go here -->
*[callback function]: Python function that Fast Dash deploys as web apps 
*[callback functions]: Python functions that Fast Dash deploys as web apps
*[Fast Components]: UI components that make up a Fast Dash app. They are wrappers around Dash components.


### 2. `FastDash` objects

The FastDash class powers all Fast Dash automated app development and deployment. As mentioned before, all the @fastdash decorator does under the hood is instantiate a `FastDash` object and call the `.run()` method.

In other words, all the discussion and arguments that can be passed to the `@fastdash` decorator are also valid for the `FastDash` class. But unlike the `@fastdash` decorator, `FastDash` class gives us access to other Fast Dash internals and flexibility concerning the deployment of our apps.

Here's how to define and deploy a Fast Dash app using FastDash. Note the highlighted differences in the code.

``` py hl_lines="6 7"
from fast_dash import FastDash

def your_function(...):
    ...

app = FastDash(callback_fn=your_function, ...)
app.run()
```

We can logically separate function definition and deployment and modify configurations beyond `FastDash`'s default arguments.

For example, we can bring our own components and layout designs by altering the UI development code, which can be accessed using `app.app.layout`.

In the [next section](components.md), we'll see what Fast Components are, what separates them from other Dash components, and how we can easily modify Dash components to make them compatible with Fast Dash.