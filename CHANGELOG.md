# Release 0.2.7

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