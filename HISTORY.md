# History

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