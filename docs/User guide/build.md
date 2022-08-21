# Under the hood

Different configurations that go into building a Fast Dash app determine the UI components, themes, how the app is deployed and the nature of user interaction.

The intention of this document is to introduce all those options so that you can make the most of Fast Dash.

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

Using the `@fastdash` decorator is the quickest way to deploy Fast Dash apps but the `FastDash` class gives us access to the other Fast Dash internals and allows us to tweak them as you see fit.

Whereas the `fastdash` decorator deploys our app at the time of defining our functions, the `FastDash` class objects are equivalent to Flask's server objects, which
allow us to deploy our app later. But we'll understand these difference better throughout the remainder of this document.

!!! note
    Both the `@fastdash` decorator and the `FastDash` class objects are functionally equivalent. The `@fastdash` decorator is internally powered by the `FastDash` class. Using decorators saves us the need to specify callback functions as the first argument when defining the `FastDash` object.


Let's first understand how to build Fast Dash apps using the `@fastdash` decorator and then extend these ideas to the `FastDash` class.

### 1. `@fastdash` decorator

#### What's a decorator?

In a nutshell, Python decorators are function wrappers that enrich the functionaltiy of Python functions. [Here's](https://realpython.com/primer-on-python-decorators/) an in-depth write-up on Python decorators, what they are and how to build them. But all that we need to know for now is that decorators, themselves, are Python functions which take other functions as arguments and add extra functionality to them.

The `@fastdash` decorator is also just a function (read more here about the implementation in the [Modules](../api.md) section) that takes the callback function as the first argument and designs a web app around it. But instead of explicitly specifying the name of the callback function as the first argument, we use this syntax instead:

```py
@fastdash(...)
def your_function(...)
    ...
```

#### How to use `@fastdash`

After we have a Python function that runs without errors, there are only two things we need to do:

#### 1.1. Specify the input and output type hints
Fast Dash uses these type hints to determine which components to use. For example, an input with the type hint `int` will need an input that allows entering integers or a slider. Similarly, an image input will need an upload image or a camera component.

!!! question "What are type hints?"
    First introduced in Python 3.5, __type hints__ are mainly meant to be used IDEs and linters to raise data type mismatch warnings. They not executed during runtime and any errors with type hinting doesn't affect the execution of the function itself. Read more about Python type hints [here](https://docs.python.org/3/library/typing.html).

    ```py
    def your_function(a: str, b: int, c: list) -> str:
        ...
    ```

    Fast Dash uses this flexbility with defining type hints to allow using Fast Components as hints. More on this in the documentation for [Fast Components](components.md).

So far, Fast Dash understands two types of type hints—one, Python in-built data type classes (`str`, `int`, `float`, `list`, `dict`, etc.), and two, [Fast Components](components.md).

In addition to type hints, the input arguments can also have default values. In the example below, the default values of integer `a` is `Fast`, that of `b` is `5` and `c` is a `list` with a default value of `[1, 2, 3]`.

```py hl_lines="1"
def your_function(a: str = "Fast", b: int = 5, c: list = [1, 2, 3]) -> str:
    ...
```

Fast Dash determines the best [Fast Components](components.md) to use for each input from their hints and default values. Details about which combination of these values result into what components are in the [patterns documentation](patterns.md).

[Fast Components](components.md) are also valid type hints for Fast Dash. Instead of depending on the hints and default values, using [Fast Components](components.md) is a direct way of telling Fast Dash which components to use. In the example below, `UploadImage` and `Slider` are in-built Fast Component wrappers for [`dcc.Upload`](https://dash.plotly.com/dash-core-components/upload) and [`dcc.Slider`](https://dash.plotly.com/dash-core-components/slider) respectively. The function returns a text field, represented using the [`html.H1`](https://dash.plotly.com/dash-html-components/h1) component by default.

```py hl_lines="1 4"
from fast_dash import fastdash, UploadImage, Slider

@fastdash
def your_function(image: UploadImage, number: Slider):
    ...
```

#### 1.2. Modify default settings

These include multiple options like the theme of the app, social media branding links, and subheaders.

##### Title

Fast Dash is able to read the title of our callback function and display it at the top of the app. Titles resolve the best if the function name is written in [snake case](https://en.wikipedia.org/wiki/Snake_case).

For example, `your_function` resolves to `Your Function` but `yourFunction` will resolve to `YourFunction`. For such cases, we can manually specify the title as an argument to `@fastdash`.

```py hl_lines="1"
@fastdash(title="Your Function")
def yourFunction(...):
    ...
```

##### Subheader

The subheader shows up below the title at the top of the page in an italicized font. Fast Dash also attempts to infer this from the function docstring. But we can also overwrite this in the `subheader` argument to `@fastdash`.

```py hl_lines="2 4"
@fastdash(title="Your Function", 
          subheader="Coolest Function Ever") # Either here
def yourFunction(...):
    "Coolest Function Ever" # or here
    ...
```

##### Title image path

Fast Dash optionally displays an icon image below the title. The image path can be set with the argument `title_image_path`.

```py hl_lines="1"
@fastdash(title_image_path="https://tinyurl.com/5fw564ux")
def yourFunction(...):
    ...
```

##### Social media URLs

We can also set social media URLs (Fast Dash supports GitHub, LinkedIn and Twitter URLs so far) in the navigation bar at the top by setting the arguments `github_url`, `linkedin_url`, and `twitter_url` respectively.

```py hl_lines="1 2 3"
@fastdash(github_url="github.com/dkedar7",
        linkedin_url="linkedin.com/in/dkedar7",
        twitter_url="twitter.com/dkedar7")
def yourFunction(...):
    ...
```

##### Navbar and footer visibility

We can hide the navbar and the footer by controlling the boolean `navbar` and `footer` arguments respectively. These are set to `True` by default.

```py hl_lines="1 2"
@fastdash(navbar=False,
        footer=False)
def yourFunction(...):
    ...
```

##### Theme

The default theme that Fast Dash uses is called `JOURNAL` but there are more themes that Fast Dash supports. See the full list of supported themes at [bootswatch.com](https://bootswatch.com/).

```py hl_lines="1"
@fastdash(theme='JOURNAL')
def yourFunction(...):
    ...
```

##### Update Live

By default, Fast Dash apps load lazily. That means once the user enters inputs, the outputs upadte only after they click `Submit`. But on setting the `update_live` argument to `True`, the `Submit` and `Reset` button disappear and the outputs update instantaneously. This feature is also popularly known as hot reloading.

```py hl_lines="1"
@fastdash(update_live=True)
def yourFunction(...):
    ...
```

##### Mode

`mode` is a very interesting argument that decides how Fast Dash apps are deployed. There are currently four supported modes. The default mode is `None` but the other possible `mode` options specified below require the [`jupyter-dash`](https://pypi.org/project/jupyter-dash/) package installed. Read more about the package [here](https://github.com/plotly/jupyter-dash).

###### `None`
By default, `mode` is set to `None` which deploys the app at the chosen port (default Dash port is 5000).

###### `JupyterLab`
When `mode` is `JupyterLab`, the app is deployed within Jupyter environments (e.g. classic Notebook, JupyterLab, Visual Studio Code notebooks, nteract, PyCharm notebooks). The app opens as a separate tab inside JupyterLab.

###### Inline
With this `mode`, Fast Dash uses an IFrame to display the application inline in the notebook.

###### External
This behaves like the default mode with the only difference that the app runs outside your Jupyter notebook environment. Fast Dash display a link that where you can navigate to see how the deployment will look to end users after this application is depoyed to production.

```py hl_lines="1"
@fastdash(mode='jupyterlab')
def yourFunction(...):
    ...
```

##### Minimal
Sometimes, we just want to see how pur Python functions behaves without worrying about the theme, or the presence of the navbar or footer. If we set `minimal` to True, Fast Dash only displays the input and output components and hides the rest.

```py hl_lines="1"
@fastdash(minimal=True)
def yourFunction(...):
    ...
```

##### Disable logs
Under the hood, setting `disable_logs` to `True` disables the messy log output that sometimes follows a successful Fast Dash deployment. This feature is very handy especially when we are deploying apps inside Jupyter enviroments. On the flip side, we lose a lot of useful debugging information.

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

The `FastDash` class powers all Fast Dash automated app development and deployment. In fact, as mentioned in a note before, all that the `@fastdash` decorator does under the hood is instantiate a `FastDash` objects and call the `.run()` method.

In other words, all the discussion and arguments that can be passed to the `@fastdash` decorator are valid to the `FastDash` class as well. But unlike the `@fastdash` decorator, `FastDash` class gives us access to other Fast Dash internals and flexibility with respect to deploying our apps.

Here's how to define and deploy a Fast Dash app using `FastDash`. Note the highlighted differences in the code.

``` py hl_lines="6 7"
from fast_dash import FastDash

def your_function(...):
    ...

app = FastDash(callback_fn=your_function, ...)
app.run()
```

We are able to logically separate function definition and deployment and additionally can modify configurations beyond what `FastDash`'s default arguments allow.

For example, we are able to bring our own components and layout designs by altering the UI development code which can be accessed using `app.app.layout`.


In the [next section](components.md), we'll see what Fast Components are, what separates them from other Dash components and how we can easily modify Dash components to make them compatible with Fast Dash.