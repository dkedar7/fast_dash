# Release 0.2.11

## 0.2.11 (2025-06-26)

### Features
- **CLI**: Add CLI project creation functionality and register script entry point
- **Notifications**: Add notify function and integrate notification handling in FastDash class
- **Callbacks**: Refactor component selection and enhance FastDash class with callback attribute for easier app interactions
- **Branding**: Add option to disable FastDash branding in the app
- **Streaming**: Add streaming functionality with socket.io support and loader support to FastDash components
- **Chat**: Enhance Chat component with streaming support, partial updates, and artifacts (Plotly figures, images, matplotlib, pandas, text)

### Improvements
- **Dependencies**: Update dependencies and improve component configurations for compatibility
- **Components**: Replace dcc.Dropdown with dmc.Select and dmc.MultiSelect for improved component handling
- **Testing**: Implement polling mechanism and improve synchronization in streaming tests

### Bug Fixes
- **Component Data**: Fix component data handling in _get_component_from_input and update tests
- **Dependencies**: Remove unused default properties for DateRangePicker and Prism components

