# History

# Release 0.2.8

## 0.2.8 (2023-12-10)

### Features

- On mobile layouts, automatically close sidebars when submit is clicked. Thank you @seanbearden for the issue.
- New examples in the documentation.
- Added some new examples to README.

### Fixes

- Set image component width to 100%.
- Fix: If input is None, it's not automatically transformed.

## 0.2.7 (2023-10-18)

### Features

- New component: `Table`
- - Fast components are callable to update attributes. For example, to update the `page_size` attribute of `Table`, do `Table(page_size=20)`. At the same time, Fast Components can also be used as non-callable objects.
- Pandas DataFrame is rendered as a `Table`.
- "About" button displays the function docstring in parse markdown. New utility function to extract function docstring has been incorporated for this feature. This is, however, still experimental.
- Documentation upates, new "Usage Patterns" page.
- New tests.
- Fast Dash now supports Python 3.11.

### Deprecations

- Support for Python 3.7 has been deprecated.

## 0.2.6 (2023-09-04)

### Features

- New chat component! Setting the output data type to `Chat` and returning a dictionary displays a chat component.
- Introduced a transformation step before passing inputs to the callback. This allows converting non-native inputs to native data types. For example, passing a PIL.Image as input data tyoe hint doesn't need converting it to a base64 string.
- Errors are displayed as notifications.
- Updated documentation and tests. 

## 0.2.5 (2023-08-13)

### Improvements

- Fix: `update_live` is automatically set to `True` if the callback function doesn't require any inputs.

## 0.2.4 (2023-08-12)

### Improvements

- Improve responsiveness on mobile views.
- `outputs` argument overrides callback function output hints.
- Improve pytest coverage.

## 0.2.3 (2023-08-01)

### Features

- Dash components can be used as type hints directly. They are converted to Fast components during app initialization.
- Added a mosaic layout example to README.
- `dash` can be imported from `fast_dash` like this: `from fast_dash import dash`.

## 0.2.2 (2023-07-26)

### Features

- New example: Chat over docs with Embedchain.

### Improvements

- Squashed a bug that was preventing the submit and reset buttons to sync with each other. The result is a more stable deploy using callback context.

## 0.2.1 (2023-07-23)

### Features

- Infer output labels from the callback function or specify the `output_labels`` argument
- Show overlay when loading outputs
- Use dmc.Burger icon instead of open, close icons. Allows for a clearner sidebar open/close UX
- New examples

### Improvements

- [Bug] Components are now initialized with the desired height
- Sidebar collapse burger is not supported in minimal layout
- Replace branding text with icon
- New pytests to improve coverage

## 0.2.0 (2023-07-02)

### Features

- Enable sidebar layout.
- Mosaic to build custom layouts.
- Collapsible sidebar.

### Improvements

- Sidebar layout improvements to allow flex sizing of components.
- Unit test updates to support the latest tox and poetry versions.

## 0.1.7 (2022-08-21)

* Introduce Fast Dash decorator (`fastdash`) for automatic and quick deployment.
* Autoinfer input and output components from type hints and default values.
* Autoinfer title and subheader by inspecting the callback function.
* New test cases.
* Modified documentation layout and content.
* New GitHub Actions workflow to publish documentation only.

## 0.1.6 (2022-05-09)

* Navbar and footer are not thinner than before, which makes them less distracting ;)
* They no longer stick to the top and bottom respectively. Scrolling on the page makes the navbar dissappear!
* Update live: New live update option! Setting the argument `update_live=True` removes `Submit` and `Clear` buttons. Any action updates the app right away.
* New spinners: Finally, Fast Dash now has loading spinners to indicate loading outputs. This comes in handy when executing long running scripts.

## 0.1.5 (2022-04-02)

* Add examples: Object detection, molecule 3D viewer and UI updates to the existing examples.
* Easier fastification: Fastify now allows using a complete Dash component as the first argument.
* Tests: Increase pytest coverage to 95%.

## 0.1.4 (2022-03-21)

* New component property allows setting "acknowledgment" component!
* Default app title is 'Prototype'.
* New UploadImage component uses another html.Img component as acknowledgment.
* Added a new Neural Style Transfer example.
* Added examples to pytest cases.

## 0.1.3 (2022-03-11)

* Added 3 new examples.
* Make `navbar` and `footer` removable from the app UI.
* Updated documentation structure.
* Added Google Cloud Run deployment docs.

## 0.1.2 (2022-03-06)

* Supports usage of the same FastComponent multiple times via deepcopy.
* Correct documentation typos and examples.
* Added text-to-text examples.
* Modifications to the Fastify component.

## 0.1.1 (2022-02-28)

* First wide release.
* Adding input, output image functionality.
* Added mkdocs documentation.

## 0.1.0 (2022-01-29)

* First release on PyPI.