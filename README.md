# Azure Functions Durable Agent Sample (Python)

This project demonstrates using the **Microsoft Agent Framework** with **Azure Functions (Python)** and the **durable task framework** to create and run durable agents.

The implementation follows the guidance in the Microsoft Learn tutorial:

> Create and run a durable agent – Microsoft Agent Framework  
> https://learn.microsoft.com/en-us/agent-framework/tutorials/agents/create-and-run-durable-agent?tabs=bash&pivots=programming-language-python

Use this README as a quick-start guide for running, debugging, and testing the project in a VS Code dev container.

---

## Prerequisites

- VS Code with **Dev Containers** support (or GitHub Codespaces)
- Docker (for running the dev container locally)
- Azure subscription (for optional/prod deployment and managed OpenAI)
- Access to an **OpenAI-compatible endpoint** (Azure OpenAI or OpenAI)

---

## Dev Container Quick Start

This repo is designed to be run inside the VS Code dev container defined in `./.devcontainer/`.

1. **Open the repo in VS Code**
   - `File` → `Open Folder...` → select `/workspaces/azure-functions-python` (or clone locally first).

2. **Reopen in Dev Container**
   - When prompted, choose **"Reopen in Container"**, or run:
     - Command Palette → `Dev Containers: Reopen in Container`.

3. **(Optional) Activate the local venv**
   - The dev container typically configures Python automatically, but you can run:
     - `source .venv/bin/activate`

4. **Install Python dependencies**
   - The workspace defines a VS Code task to install dependencies:
     - Command Palette → `Tasks: Run Task` → `pip install (functions)`
     - Or in a terminal: `python -m pip install -r requirements.txt`

---

## OpenAI Endpoint Requirements

The agent implementation depends on an OpenAI-compatible model endpoint. You have two main options:

### 1. Use an existing / manually-created OpenAI endpoint

You can point the function app at:

- An **Azure OpenAI** resource, or
- An **OpenAI** endpoint (or other OpenAI-compatible service)

You will need at minimum:

- Endpoint URL
- API key
- Model / deployment name

These values must be configured in `local.settings.json` (see **Configuration** below).

### 2. Deploy infrastructure with Bicep

The `./infra/` directory contains Bicep templates to provision the required Azure resources, including OpenAI and related access:

- `infra/main.bicep` – main entry point
- `infra/main.parameters.json` – sample parameters
- `infra/app/*.bicep` – app-specific infrastructure
- `infra/ai/*.bicep` – cognitive / OpenAI resources
- `infra/rbac/*.bicep` – access management

At a high level, you can deploy with Azure CLI (from the dev container, or your local environment):

```bash
az group create -n <resource-group-name> -l <region>
az deployment group create \
  -g <resource-group-name> \
  -f infra/main.bicep \
  -p @infra/main.parameters.json
```

After deployment, copy the relevant endpoint, keys, and resource names into your `local.settings.json` file.

---

## Local Configuration (`local.settings.json`)

Runtime and secret configuration is managed via `local.settings.json`. A sample file is provided at `./local.settings.sample.json`.

1. **Create your local settings file**

```bash
cp local.settings.sample.json local.settings.json
```

2. **Edit `local.settings.json`**

Update the values to match your OpenAI or Azure OpenAI setup (and any other required settings in this repo), for example:

- `AZURE_OPENAI_ENDPOINT`
- `AZURE_OPENAI_API_KEY`
- `AZURE_OPENAI_DEPLOYMENT`
- Any other app-specific configuration keys defined in `function_app.py` or the sample settings file.

> `local.settings.json` is for local development only and should not be checked into source control.

---

## Running the Durable Agent Locally

The project is an Azure Functions Python app configured for **durable functions / agents** via the Microsoft Agent Framework.

1. **Start the Functions host**

- Use the VS Code task:
  - Command Palette → `Tasks: Run Task` → `func: host start`

  This will:

  - Ensure dependencies are installed via `pip install (functions)`
  - Start the local Azure Functions host.

- Or run manually (if the Azure Functions Core Tools are available in the dev container):

```bash
func host start
```

2. **Verify Functions are running**

The host will print the list of HTTP triggers and their local URLs. These endpoints are used in `test.http` and for debugging.

---

## Debugging with VS Code (F5)

You can debug the functions and the durable agent orchestration directly in VS Code.

1. Open the workspace in VS Code dev container.
2. Ensure `local.settings.json` is configured correctly.
3. Press `F5` (or go to `Run and Debug` → `Start Debugging`).
4. Select the **Azure Functions** debug configuration if prompted.
5. VS Code will:
   - Build and start the Functions host.
   - Attach the Python debugger.

You can set breakpoints in:

- `function_app.py` (HTTP starter, orchestrator, activity functions)
- Any other Python modules used by your agent.

When you send requests (see **Testing**), execution will stop on your breakpoints.

---

## Testing with `test.http`

The file `./test.http` contains example HTTP requests for testing the durable agent endpoints.

To use it:

1. Open `test.http` in VS Code.
2. Ensure the Functions host is running (via task or F5 debugging).
3. Hover over a request in `test.http` and click **"Send Request"** (requires the REST Client extension or VS Code HTTP tooling).
4. Inspect the responses for:
   - Starting a new durable agent / orchestration
   - Querying status
   - Sending input/messages to the agent (depending on the implementation)

You can adapt these sample requests to exercise different scenarios or payloads supported by your agent implementation.
