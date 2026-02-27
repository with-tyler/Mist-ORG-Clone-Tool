# POC Demo Org — Mist Org Cloner

A command-line tool that clones a Juniper Mist organization — including sites, org-level templates, site settings, sitegroup memberships, alarm templates, and more — from one Mist environment to another. Designed for pre-sales and demo use, it walks you through the entire process interactively with no coding required.

---

## Table of Contents

- [POC Demo Org — Mist Org Cloner](#poc-demo-org--mist-org-cloner)
  - [Table of Contents](#table-of-contents)
  - [Access Assurance (NAC) Cloning](#access-assurance-nac-cloning)
    - [What is cloned automatically](#what-is-cloned-automatically)
    - [What requires manual action after cloning](#what-requires-manual-action-after-cloning)
  - [What This Tool Does](#what-this-tool-does)
  - [What Gets Cloned](#what-gets-cloned)
  - [Before You Begin — Prerequisites](#before-you-begin--prerequisites)
  - [Step 1 — Install Python](#step-1--install-python)
    - [macOS](#macos)
    - [Windows](#windows)
  - [Step 2 — Download This Project](#step-2--download-this-project)
  - [Step 3 — Set Up a Virtual Environment (Recommended)](#step-3--set-up-a-virtual-environment-recommended)
  - [Step 4 — Install Required Packages](#step-4--install-required-packages)
  - [Step 5 — Set Up Your API Key (config.ini)](#step-5--set-up-your-api-key-configini)
    - [Getting your Mist API token](#getting-your-mist-api-token)
    - [Editing config.ini](#editing-configini)
    - [Which `base_url` should I use?](#which-base_url-should-i-use)
  - [Step 6 — Run the Tool](#step-6--run-the-tool)
    - [Guided Walkthrough](#guided-walkthrough)
      - [1. Select API Profile](#1-select-api-profile)
      - [2. Select Destination (Same Cloud or Cross-Cloud)](#2-select-destination-same-cloud-or-cross-cloud)
      - [3. Source Configuration](#3-source-configuration)
      - [4. Configure Sites](#4-configure-sites)
      - [5. Template Assignment Mode](#5-template-assignment-mode)
      - [6. Preflight Check](#6-preflight-check)
      - [7. Confirm and Clone](#7-confirm-and-clone)
      - [8. Run Log](#8-run-log)
  - [Template Assignment Modes — Explained](#template-assignment-modes--explained)
    - [Mode 1 — Select per site (manual)](#mode-1--select-per-site-manual)
    - [Mode 2 — Select once for all sites (default)](#mode-2--select-once-for-all-sites-default)
    - [Mode 3 — Single template per type](#mode-3--single-template-per-type)
    - [Mode 4 — Auto-match from source](#mode-4--auto-match-from-source)
  - [Cross-Cloud Cloning](#cross-cloud-cloning)
  - [Command-Line Options](#command-line-options)
  - [Troubleshooting](#troubleshooting)
    - ["python3: command not found" or "'python' is not recognized"](#python3-command-not-found-or-python-is-not-recognized)
    - ["pip: command not found"](#pip-command-not-found)
    - ["ModuleNotFoundError: No module named 'requests'"](#modulenotfounderror-no-module-named-requests)
    - ["401 Unauthorized" or "403 Forbidden" from the API](#401-unauthorized-or-403-forbidden-from-the-api)
    - [The tool exits immediately or shows an error before any prompts](#the-tool-exits-immediately-or-shows-an-error-before-any-prompts)
    - [A template is skipped with "not found in target org"](#a-template-is-skipped-with-not-found-in-target-org)
    - [Cross-cloud clone stops partway through](#cross-cloud-clone-stops-partway-through)

---

## Access Assurance (NAC) Cloning

After the main org and site structure is cloned, the tool offers to clone your full **Access Assurance / NAC** configuration. You will be prompted to confirm before this phase runs — you can skip it entirely if your destination org does not use NAC.

### What is cloned automatically

| Resource | Notes |
|---|---|
| NAC Org Settings | The `mist_nac` block from org-level settings |
| SCEP Configuration | Copied if enabled in the source org |
| SSO Roles | Copied; IDs remapped in dependent SSO records |
| SSOs (Identity Providers) | Copied with SSO Role IDs remapped |
| NAC Tags | Copied; IDs remapped in rules and portals |
| NAC Rules | Copied with all NAC Tag references updated to destination IDs |
| NAC Portals | Copied with NAC Tag and SSO references updated |
| PSK Portals | Copied; the org-specific portal URL (`ui_url`) is stripped automatically |
| User MACs | Optional — you will be asked separately during the NAC phase |

### What requires manual action after cloning

Some NAC items are **org-specific** and cannot be transferred automatically. The tool will print a clear notice for each of these during the run, including the exact Mist UI path where you need to act.

| Item | Why it cannot be cloned | Where to fix it |
|---|---|---|
| **SAML / SP Metadata** | Each org generates its own unique SP Entity ID, ACS URL, and signing certificate | Mist UI → Organization → Access → SSOs → (select SSO) → Download SP Metadata, then re-register with your IdP |
| **SSO / IDP Allowable Domains** | Not included in the SSO endpoint payload | Mist UI → Organization → Access → SSOs → (select SSO) → Allowable Domains |
| **SCEP CA Certificate** | A new CA certificate is generated automatically per org | Mist UI → Organization → Access → Access Assurance → SCEP → Download CA Cert, then distribute to devices |
| **CRL Files** | Binary upload — cannot be transferred via the API | Mist UI → Organization → Access → Access Assurance → Certificates → Upload CRL |
| **NAC Portal Branding Images** | Binary upload — cannot be transferred via the API | Mist UI → Organization → Access → Access Assurance → Portals → (select portal) → Branding |
| **PSK Portal Branding Images** | Binary upload — cannot be transferred via the API | Mist UI → Organization → Access → PSK Portals → (select portal) → Branding |
| **PSK Portal SSO / SP Metadata** | Each PSK portal with SSO auth generates a unique SP Entity ID and ACS URL per org | Mist UI → Organization → Access → PSK Portals → (select portal) → Download SP Metadata, then re-register with your IdP |
| **RADIUS Shared Secrets / IDP Credentials** | Copied as placeholders; actual secrets are not exposed by the API | Mist UI → Organization → Access → Access Assurance → Settings — verify and re-enter credentials |

> **Tip:** The tool prints a detailed action-required notice for each of the above items as it encounters them. Save the run log (see [Run Log](#8-run-log)) to keep a checklist of everything that needs manual attention.

---

## What This Tool Does

This tool connects to the **Juniper Mist API** and automates the full process of cloning an existing Mist organization into a brand-new one. It can clone to the **same Mist cloud** instance (fast, server-side) or across **different cloud regions** (e.g., Global 01 → Global 03).

The tool is fully interactive — every step presents a menu or prompt. No scripting or editing files mid-run is required.

---

## What Gets Cloned

| Resource | Notes |
|---|---|
| **Organization structure** | Name, settings, and all org-level configuration |
| **Site groups** | Matched by name; site memberships restored per site |
| **Service policies** | Copied to the new org; IDs remapped in gateway templates |
| **Switch templates** (network templates) | Copied and reassigned to sites by name |
| **WAN edge / gateway templates** | Copied with service policy IDs remapped |
| **WLAN templates** | Copied; org-wide and site-level scope both handled |
| **RF templates** | Copied and reassigned to sites by name |
| **Alarm templates** | Copied to the new org and reassigned to sites by name |
| **Site settings** | Copied per site (read-only and template ID fields stripped and re-applied) |
| **Site-specific WLANs** | Copied from each source site to the corresponding new site |
| **Super user invites** | Optional; invited to the new org with admin role |
| **NAC SSO Roles** | Copied to the new org; ID references remapped in dependent resources |
| **NAC SSOs (Identity Providers)** | Copied with SSO Role IDs remapped; see [NAC notes](#access-assurance-nac-cloning) |
| **NAC Tags** | Copied; ID references remapped in rules and portals |
| **NAC Rules** | Copied with NAC Tag IDs remapped |
| **NAC Portals** | Copied with NAC Tag and SSO IDs remapped; see [NAC notes](#access-assurance-nac-cloning) |
| **NAC Org Settings** | The `mist_nac` block is copied from org settings |
| **SCEP configuration** | Copied if enabled; see [NAC notes](#access-assurance-nac-cloning) |
| **User MACs** | Optional; prompted separately during the NAC phase |
| **PSK Portals** | Copied; see [NAC notes](#access-assurance-nac-cloning) for manual post-clone steps |

---

## Before You Begin — Prerequisites

| Requirement | Notes |
|---|---|
| macOS, Windows, or Linux | ✅ |
| Internet connection | ✅ |
| Juniper Mist account with **Org Admin** access | Required to clone org-level resources |
| Mist API token | Get one from **My Profile → API Token** in the Mist portal |
| Python 3.9 or newer | See [Step 1](#step-1--install-python) |

---

## Step 1 — Install Python

Python is a free programming language this tool is built on. You do **not** need to know how to code — you just need it installed.

### macOS

1. Open **Terminal** (`⌘ + Space` → type `Terminal` → Enter).
2. Check if Python is already installed:
   ```
   python3 --version
   ```
   If you see `Python 3.x.x`, skip to [Step 2](#step-2--download-this-project).
3. If not installed, download the official installer from **https://www.python.org/downloads/**, open the `.pkg` file, and follow the instructions.
4. Re-run the version check to confirm.

### Windows

1. Open **Command Prompt** (`Windows Key` → type `cmd` → Enter).
2. Check:
   ```
   python --version
   ```
   If you see `Python 3.x.x`, skip to [Step 2](#step-2--download-this-project).
3. Download from **https://www.python.org/downloads/** and run the installer.
   > **Important:** On the first installer screen, tick **"Add Python to PATH"** before clicking Install Now.
4. Re-run the version check to confirm.

---

## Step 2 — Download This Project

**Option A — ZIP file:**
Unzip the project to a folder you can easily find (e.g., your Desktop), producing a folder called `POC_DEMO_ORG`.

**Option B — Git:**
```
git clone https://github.com/with-tyler/POC_DEMO_ORG.git
cd POC_DEMO_ORG
```

After this step the folder should contain: `poc_clone_org.py`, `requirements.txt`, `config.ini`, `example_config.ini`, and others.

---

## Step 3 — Set Up a Virtual Environment (Recommended)

A virtual environment keeps this project's dependencies isolated from the rest of your system. This is optional but strongly recommended.

**macOS / Linux:**
```
cd ~/Desktop/POC_DEMO_ORG
python3 -m venv .venv
source .venv/bin/activate
```

**Windows:**
```
cd C:\Users\YourName\Desktop\POC_DEMO_ORG
python -m venv .venv
.venv\Scripts\activate
```

Your terminal prompt will change to show `(.venv)` when the environment is active. Run all subsequent commands from this same terminal session.

> To deactivate the virtual environment when you're done, type `deactivate`.

---

## Step 4 — Install Required Packages

With your terminal open in the `POC_DEMO_ORG` folder (and the virtual environment active if you set one up), run:

**macOS / Linux:**
```
pip3 install -r requirements.txt
```

**Windows:**
```
pip install -r requirements.txt
```

This downloads and installs all required libraries listed in `requirements.txt`. You only need to do this **once** (or whenever `requirements.txt` changes).

---

## Step 5 — Set Up Your API Key (config.ini)

The tool reads your Mist API credentials from `config.ini` in the project folder.

### Getting your Mist API token

1. Log in to your Mist portal (e.g., `manage.mist.com`).
2. Click your name in the top-right corner → **My Profile**.
3. Scroll to **API Token** and copy the token value.

### Editing config.ini

Open `config.ini` in any plain-text editor. It looks like this:

```ini
[GLOBAL01]
api_token = YOUR_API_TOKEN_HERE
base_url = https://api.mist.com/api/v1
```

Replace `YOUR_API_TOKEN_HERE` with your actual token. **Do not add quotes or extra spaces.**

### Which `base_url` should I use?

| Mist Cloud | `base_url` |
|---|---|
| Global 01 (US) | `https://api.mist.com/api/v1` |
| Global 02 (EU) | `https://api.eu.mist.com/api/v1` |
| Global 03 | `https://api.ac2.mist.com/api/v1` |
| Global 04 | `https://api.gc2.mist.com/api/v1` |

**Multiple profiles:** You can add as many sections as you like — one per cloud environment. Give each a unique name in square brackets, for example `[GLOBAL03]`. You will be prompted to choose which profile to use at runtime.

> **Security:** Keep your API token private. Do not share `config.ini` or commit it to a public repository. The file `example_config.ini` is provided as a blank reference.

> **Tip:** You can also create or manage profiles interactively by running `python3 poc_clone_org.py --init`, or by selecting "Add or manage API key profiles?" at the first prompt when the tool starts.

---

## Step 6 — Run the Tool

With your terminal in the `POC_DEMO_ORG` folder:

**macOS / Linux:**
```
python3 poc_clone_org.py
```

**Windows:**
```
python poc_clone_org.py
```

The tool starts in **guided mode** and walks you through each step. At any prompt, press **Enter** to accept the default shown in brackets.

---

### Guided Walkthrough

#### 1. Select API Profile

The tool reads `config.ini` and displays all configured profiles. Select the profile (cloud instance) that matches your **source** organization.

If no profiles exist yet, you will be prompted to add one before continuing.

---

#### 2. Select Destination (Same Cloud or Cross-Cloud)

```
Clone Mode:
  1. Same cloud instance (default)
  2. Different cloud instance (cross-cloud)
```

- **Option 1** — Clone within the same Mist cloud. Uses the fast Mist server-side `/clone` endpoint, then applies any missing resources on top.
- **Option 2** — Clone to a different Mist cloud region. You will be prompted to select a second API profile for the destination. All resources are copied manually (no server-side clone). See [Cross-Cloud Cloning](#cross-cloud-cloning) for details.

---

#### 3. Source Configuration

The tool lists all organizations your API token can access. Select your **source organization**.

Next, choose your **site clone mode**:

```
Site Clone Mode:
  1. Clone a single site
  2. Clone all sites in the org
```

- **Mode 1** — You will be shown a list of sites and pick one.
- **Mode 2** — All sites in the source org will be cloned.

Then provide the **new organization name** for the destination org.

You will also be asked whether to **invite super users** to the new org. If yes, enter each user's email address (and optionally first/last name). Super users receive an admin invite to the new organization.

---

#### 4. Configure Sites

For each site being cloned you will be asked:

| Prompt | Default | Notes |
|---|---|---|
| Use source site name/address? | Yes | Copies name, address, and country code from the source site |
| New site name | Source site name | Only asked if you choose not to keep the source details |
| New site address | Source site address | Street address used for location context in Mist |
| Country code | Source country code | Two-letter code, e.g. `US`, `GB`, `DE` |

When cloning **all sites**, you will first be offered a batch option to apply name/address choices to every site at once, saving time.

---

#### 5. Template Assignment Mode

After configuring sites, you choose how templates are assigned:

```
Template Assignment Mode:
  1. Clone all templates — select assignments per site
  2. Clone all templates — select one template per type for all sites
  3. Clone a single template per type (select once), assign to all sites
  4. Match each site to its current templates
```

See [Template Assignment Modes — Explained](#template-assignment-modes--explained) for a full breakdown of each option.

---

#### 6. Preflight Check

Before any changes are made, the tool runs a **preflight check** and displays a summary including:

- Source org and site details
- All templates found (switch, WAN edge, WLAN, RF, alarm)
- Service policies
- Site group memberships
- Any template assignment warnings (e.g., a source template not found in the destination org)

You will be asked whether to save this summary to a JSON file (`preflight_report.json` by default).

To run **only** the preflight with no changes, use the `--dry-run` flag (see [Command-Line Options](#command-line-options)).

---

#### 7. Confirm and Clone

A final confirmation prompt shows the clone mode and destination. Enter `y` to proceed or `n` to abort — **no changes are made until you confirm**.

Once confirmed, the tool runs through all steps automatically and prints the result of each action (created, copied, assigned, or skipped with a reason).

During the **Access Assurance (NAC)** phase you will be asked:

```
? Clone Access Assurance (NAC) configuration? (Y/n)
```

Enter `y` to clone all NAC resources, or `n` to skip the entire NAC phase. If you choose `y`, you will also be asked whether to clone **User MACs** (a potentially large dataset that is optional for most demo scenarios).

---

#### 8. Run Log

At the end of every run (including dry-run and aborted runs) you will be asked:

```
? Save a full run log to a Markdown file? (Y/n)
  → clone_log.md
```

Enter `y` and accept or change the filename. The tool writes a **Markdown file** containing everything printed during the run — every success, warning, informational message, and user choice. This is especially useful for keeping track of:

- Which resources were cloned and which were skipped
- All **manual action items** flagged during NAC cloning (SAML metadata, allowable domains, CRL files, etc.)
- The selections you made (template assignments, site names, etc.)

This log is separate from the preflight JSON report. The preflight report is a machine-readable snapshot of the source org; the run log is a human-readable record of the entire cloning session.

---

## Template Assignment Modes — Explained

Templates are org-level resources in Mist. When a new org is created, all templates are copied over, but the *assignment* of those templates to sites must be re-established. The four modes control how that happens.

### Mode 1 — Select per site (manual)

You are shown the full list of available templates for each template type (switch, WAN edge, WLAN, RF) and choose which to assign to **each site individually**. At the start of the run you can optionally choose one selection to apply to all sites, which skips per-site prompts.

**Best for:** A small number of sites with different template needs, or when you want full control.

### Mode 2 — Select once for all sites (default)

You choose one template per type (switch, WAN edge, WLAN, RF) once, and that selection is applied to **every site** in the clone run.

**Best for:** Most standard use cases where all sites should share the same template set.

### Mode 3 — Single template per type

Like Mode 2 — you select one template per type once and that selection is applied to every site. The full set of org-level templates is still cloned to the new org.

**Best for:** Situations where all sites should share the same template set (same outcome as Mode 2).

### Mode 4 — Auto-match from source

The tool reads each **source site's current template assignments**, looks up the corresponding templates in the new org by name, and applies them automatically — no manual selection required.

- Switch, WAN edge, and RF templates are read directly from site settings.
- WLAN templates are resolved by cross-referencing the source org's template `applies` scope (site-level vs. org-wide).
- Alarm templates are always auto-matched by name in all modes.

If a source template name is not found in the destination org (e.g., it was renamed), the tool logs a warning and skips that assignment.

**Best for:** Same-cloud clones where the destination org already has matching templates (e.g., after a server-side clone), and you want assignments to mirror the source exactly.

---

## Cross-Cloud Cloning

When cloning to a **different Mist cloud** (Mode 2 at the destination prompt), the server-side `/clone` endpoint is not available. The tool instead:

1. Creates a blank org on the destination cloud.
2. Copies all of the following **in order**:
   - Site groups
   - Service policies
   - Switch templates (network templates)
   - RF templates
   - WLAN templates
   - WAN edge / gateway templates (with service policy IDs remapped to destination IDs)
   - Alarm templates
3. Then proceeds with the standard per-site creation loop (settings, WLANs, sitegroup membership, template assignment).

You need a valid API token in `config.ini` for **both** the source and destination cloud regions.

---

## Command-Line Options

| Flag | What it does |
|---|---|
| *(no flags)* | Launches the interactive guided flow |
| `--guided` | Same as running with no flags |
| `--dry-run` | Runs all preflight checks but makes **zero changes** to Mist |
| `--preflight-json` | Saves the preflight report to `preflight_report.json` automatically |
| `--preflight-json <filename>` | Saves the preflight report to a custom filename |
| `--init` | Opens the interactive API key wizard to create or update `config.ini` |
| `--init-from-env` | Reads `MIST_API_TOKEN` and `MIST_BASE_URL` from environment variables and writes `config.ini` |

**Examples:**

```
# Dry run only — no changes applied, report saved automatically
python3 poc_clone_org.py --dry-run --preflight-json

# Save the preflight report to a custom file
python3 poc_clone_org.py --preflight-json my_report.json

# Add or update an API key profile
python3 poc_clone_org.py --init

# Create config.ini from environment variables (useful in CI/CD)
export MIST_API_TOKEN=your_token_here
export MIST_BASE_URL=https://api.mist.com/api/v1
python3 poc_clone_org.py --init-from-env
```

---

## Troubleshooting

### "python3: command not found" or "'python' is not recognized"

Python is not installed or not on your PATH. Revisit [Step 1](#step-1--install-python). On Windows, ensure you checked **Add Python to PATH** during installation.

### "pip: command not found"

Try `pip3` instead of `pip` (macOS/Linux). Alternatively, use `python3 -m pip install -r requirements.txt`.

### "ModuleNotFoundError: No module named 'requests'"

Packages have not been installed, or you are not in the virtual environment. Activate the virtual environment (see [Step 3](#step-3--set-up-a-virtual-environment-recommended)) and re-run the install command from [Step 4](#step-4--install-required-packages).

### "401 Unauthorized" or "403 Forbidden" from the API

Your API token is incorrect, expired, or does not have Org Admin privileges. Verify the token value in `config.ini` and that the `base_url` matches your Mist cloud region.

### The tool exits immediately or shows an error before any prompts

Make sure your terminal is in the `POC_DEMO_ORG` folder before running. Use `cd` to navigate there first. Confirm `poc_clone_org.py` is present with `ls` (macOS/Linux) or `dir` (Windows).

### A template is skipped with "not found in target org"

This appears in Mode 4 when a source template name does not exactly match any template in the destination org. Check for name differences between source and destination, or use Mode 1 or 2 to manually select the correct template.

### Cross-cloud clone stops partway through

Each resource type is copied independently. If one template fails it is skipped with a warning and the run continues. Check the output for any lines beginning with `WARN` to see what was skipped and why.

---

*For questions or issues, open a GitHub issue at [github.com/with-tyler/POC_DEMO_ORG](https://github.com/with-tyler/POC_DEMO_ORG).*
