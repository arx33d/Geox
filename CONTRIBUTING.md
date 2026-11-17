# Contributing to Geox

Thank you for your interest in contributing to Geox. We welcome issues, bug fixes, documentation improvements, and feature enhancements.

## Development Setup

1. **Clone the repository**:
   ```bash
   git clone https://github.com/arx33dbu/geox-BU.git
   cd geox-BU
   ```

2. **Create and activate a virtual environment**:
   ```bash
   python -m venv .venv
   # Windows PowerShell:
   .\.venv\Scripts\Activate.ps1
   # macOS / Linux:
   source .venv/bin/activate
   ```

3. **Install dependencies and development tools**:
   ```bash
   python -m pip install --upgrade pip
   python -m pip install -r requirements.txt
   python -m pip install ruff pytest mypy black
   ```

4. **Compile Windows native binaries (Windows only)**:
   ```powershell
   powershell -ExecutionPolicy Bypass -File .\tools\build_windows.ps1
   ```

## Running Tests and Quality Checks

Before submitting a pull request, ensure all tests and linter checks pass:

- **Run unit test suite**:
  ```bash
  python -m unittest discover tests
  ```
  *(or `pytest`)*

- **Run linter**:
  ```bash
  ruff check geox tests
  ```

- **Format check**:
  ```bash
  ruff format --check geox tests
  ```

## Commit Message Guidelines

We follow the [Conventional Commits](https://www.conventionalcommits.org/) specification:

```
<type>(<scope>): <subject>
```

### Common Types:
- `feat`: A new feature or capability
- `fix`: A bug fix
- `docs`: Documentation changes only
- `test`: Adding or updating tests
- `refactor`: Code change that neither fixes a bug nor adds a feature
- `perf`: Performance improvement
- `chore`: Changes to build process, CI workflows, or dependencies

### Examples:
- `fix(launcher): resolve port contention on server startup`
- `feat(ios): add automatic failover to wireless tunnel`
- `docs(readme): add troubleshooting section for developer mode`
- `ci(github): add matrix tests for Python 3.10 through 3.12`

## Pull Request Guidelines

1. Create a feature branch from `main`:
   ```bash
   git checkout -b feat/your-feature-name
   ```
2. Make your changes with focused, descriptive commits.
3. Verify that all 35+ unit tests pass.
4. Push your branch and open a pull request against `main`.
5. Fill out the pull request template completely.
6. A maintainer will review your pull request within 48 hours.
