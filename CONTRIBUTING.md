# Contributing to IntelligenceBox Plugins

We love your input! We want to make contributing to this project as easy and transparent as possible, whether it's:

- Reporting a bug
- Discussing the current state of the code
- Submitting a fix
- Proposing new features
- Becoming a maintainer

## We Develop with Github
We use GitHub to host code, to track issues and feature requests, as well as accept pull requests.

## We Use [Github Flow](https://guides.github.com/introduction/flow/index.html)
Pull requests are the best way to propose changes to the codebase. We actively welcome your pull requests:

1. Fork the repo and create your branch from `main`.
2. If you've added code that should be tested, add tests.
3. If you've changed APIs, update the documentation.
4. Ensure the test suite passes.
5. Make sure your code lints.
6. Issue that pull request!

## Any contributions you make will be under the MIT Software License
In short, when you submit code changes, your submissions are understood to be under the same [MIT License](LICENSE) that covers the project. Feel free to contact the maintainers if that's a concern.

## Report bugs using Github's [issues](https://github.com/intelligencebox-repo/intelligencebox-plugins/issues)
We use GitHub issues to track public bugs. Report a bug by [opening a new issue](https://github.com/intelligencebox-repo/intelligencebox-plugins/issues/new); it's that easy!

## Write bug reports with detail, background, and sample code

**Great Bug Reports** tend to have:

- A quick summary and/or background
- Steps to reproduce
  - Be specific!
  - Give sample code if you can
- What you expected would happen
- What actually happens
- Notes (possibly including why you think this might be happening, or stuff you tried that didn't work)

## Adding a New MCP Server

To add a new MCP server to this repository:

1. Create a new directory under `servers/` with your server name
2. Include the following files:
   - `Dockerfile` - For building the container
   - `package.json` - Node.js dependencies
   - `index.js` - Main server implementation
   - `README.md` - Documentation for your server
   - `manifest.json` - MCP manifest file

3. Update the registry with your new server:
   ```bash
   cd registry-cli
   npm run build
   node dist/index.js add --id your-server-id --name "Your Server Name" --docker-image ghcr.io/intelligencebox-repo/your-server:latest
   ```

## License
By contributing, you agree that your contributions will be licensed under its MIT License.