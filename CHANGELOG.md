# Release 0.2.6

## 0.2.6 (2023-09-04)

### Features

- New chat component! Setting the output data type to `Chat` and returning a dictionary displays a chat component.
- Introduced a transformation step before passing inputs to the callback. This allows converting non-native inputs to native data types. For example, passing a PIL.Image as input data tyoe hint doesn't need converting it to a base64 string.
- Errors are displayed as notifications.
- Updated documentation and tests. 