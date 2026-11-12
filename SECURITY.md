# Security Policy & Hardening Guide

This document describes how to **report security vulnerabilities** in this repository and how to **deploy, operate, and extend FastSAM** with security in mind. It is tailored to this codebase (`morphiens/FastSAM`, based on [CASIA-IVA-Lab/FastSAM](https://github.com/CASIA-IVA-Lab/FastSAM)) and synthesizes industry guidance from OWASP, NIST, MITRE ATLAS, OpenSSF, CISA, PyTorch, Gradio, and related sources.

**Last updated:** 2026-03-22  
**Audience:** maintainers, integrators, security reviewers, and operators hosting inference (CLI, Gradio, Cog/Replicate, custom APIs).

---

## Table of contents

1. [Reporting a vulnerability](#reporting-a-vulnerability)
2. [Supported versions](#supported-versions)
3. [Scope and trust boundaries](#scope-and-trust-boundaries)
4. [Architecture and attack surface](#architecture-and-attack-surface)
5. [Threat model (summary)](#threat-model-summary)
6. [Repository-specific risks](#repository-specific-risks)
7. [Controls by lifecycle phase](#controls-by-lifecycle-phase)
8. [Deployment hardening](#deployment-hardening)
9. [Supply chain and model integrity](#supply-chain-and-model-integrity)
10. [Adversarial ML and privacy](#adversarial-ml-and-privacy)
11. [Dependency and configuration security](#dependency-and-configuration-security)
12. [Incident response](#incident-response)
13. [Security checklist](#security-checklist)
14. [References](#references)

---

## Reporting a vulnerability

We follow [coordinated vulnerability disclosure](https://oss-vulnerability-guide.openssf.org/) practices ([OpenSSF Vulnerability Guide](https://github.com/ossf/oss-vulnerability-guide)).

### Preferred channels

1. **GitHub Private Vulnerability Reporting** (if enabled on `morphiens/FastSAM`):  
   Repository → **Security** → **Report a vulnerability**.

2. **Email** (if private reporting is unavailable): contact the repository maintainers at a dedicated security address.  
   *Maintainers: replace this placeholder with `security@your-domain.example` and enable GitHub Private Vulnerability Reporting.*

### What to include

- Affected component (e.g. `app_gradio.py`, `ultralytics/nn/tasks.py`, `predict.py`)
- Steps to reproduce and proof-of-concept (if available)
- Impact assessment (confidentiality, integrity, availability)
- Version/commit hash and deployment context (local Gradio, Docker/Cog, etc.)

### Our commitments

| Stage | Target |
|--------|--------|
| Initial acknowledgment | Within **5 business days** |
| Triage and severity assignment | Within **10 business days** |
| Fix or mitigation plan | Depends on severity; critical issues prioritized |
| Coordinated disclosure | After a fix or documented workaround is available |

Please **do not** open public GitHub issues for unpatched security bugs. We credit reporters in the advisory when permitted.

---

## Supported versions

| Component | Support notes |
|-----------|----------------|
| Default branch (`main`) | Active development; security fixes land here first |
| Released tags | Support only the latest tag unless otherwise documented |
| Upstream CASIA-IVA-Lab/FastSAM | This fork may diverge; report issues against **this** repository when using `morphiens/FastSAM` |

Security fixes may not be backported to unmaintained dependency pins (e.g. pinned `gradio==3.35.2`) without a deliberate upgrade path.

---

## Scope and trust boundaries

### In scope

- Python package and inference entry points: `Inference.py`, `fastsam/`, `segpredict.py`, `predict.py` (Cog)
- Demo and serving: `app_gradio.py`, `utils/tools.py`, bundled `ultralytics/`
- Model checkpoint loading (`*.pt`) and optional CLIP text mode
- Training/dataset utilities under `ultralytics/yolo/data/` when used from this repo

### Out of scope (unless explicitly integrated by you)

- Third-party hosted demos (Hugging Face Spaces, Replicate) operated by external accounts
- Arbitrary user-written wrappers not in this repository
- GPU driver / host OS hardening (documented as operator responsibility)

### Trust assumptions

| Asset | Trust level | Notes |
|-------|-------------|--------|
| Official `FastSAM.pt` / `FastSAM-s.pt` from documented release URLs | Medium | Verify checksums; treat as **executable code** once loaded ([PyTorch security policy](https://github.com/pytorch/pytorch/security/policy)) |
| User-supplied images | **Untrusted** | Size, format, and metadata must be validated for any network-facing service |
| User-supplied prompts (`text_prompt`, CLI JSON strings) | **Untrusted** | Length limits and abuse detection recommended |
| User-supplied model paths (`--model_path`) | **Untrusted** in multi-tenant settings | Path allowlists required |
| Ultralytics HUB API keys / W&B tokens | **Secret** | Environment variables only; never commit |
| Dataset YAML `download` scripts from internet | **Untrusted until reviewed** | See [dataset auto-download](#dataset-auto-download-and-dynamic-code) |

---

## Architecture and attack surface

FastSAM performs **instance segmentation** (YOLOv8-seg style backbone) with optional **CLIP** grounding for text prompts. Primary surfaces:

```text
                    ┌─────────────────────────────────────────┐
                    │           Operator / Integrator          │
                    └─────────────────────────────────────────┘
                                        │
        ┌───────────────────────────────┼───────────────────────────────┐
        ▼                               ▼                               ▼
  Inference.py                   app_gradio.py                    predict.py (Cog)
  (CLI, local paths)             (HTTP, uploads)                  (container API)
        │                               │                               │
        └───────────────────────────────┼───────────────────────────────┘
                                        ▼
                          fastsam.model.FastSAM / YOLO
                                        │
                          torch_safe_load(.pt)  ← pickle-capable load
                                        ▼
                    GPU/CPU inference + OpenCV/Pillow I/O
```

**High-value attacker goals:** GPU/CPU exhaustion, arbitrary file read via paths, RCE via malicious checkpoints or YAML, SSRF via Gradio misconfiguration, data exfiltration from uploaded images, model extraction via high-volume queries.

---

## Threat model summary

Aligned with [MITRE ATLAS](https://atlas.mitre.org/) (Predictive AI) and [NIST AI RMF](https://www.nist.gov/publications/artificial-intelligence-risk-management-framework-ai-rmf-10):

| Category | Relevant techniques | FastSAM relevance |
|----------|---------------------|-------------------|
| Supply chain | Poisoned weights, typosquat deps, unsigned artifacts | `.pt` checkpoints; `pip` + git CLIP; vendored `ultralytics/` |
| Evasion | Adversarial patches/perturbations | Segmentation masks can be manipulated ([CVPR 2018](https://doi.org/10.1109/cvpr.2018.00099), [ICCV 2017](https://doi.org/10.1109/iccv.2017.300)) |
| Availability | Resource exhaustion | Large images, many masks, unbounded Gradio queue |
| ML privacy | Membership / model inversion | Public APIs returning masks + scores ([arXiv:2212.01082](https://arxiv.org/html/2212.01082)) |
| Application | Injection, misconfiguration | `eval` in CLI config paths; Gradio defaults ([Trail of Bits Gradio audit](https://blog.trailofbits.com/2024/10/10/auditing-gradio-5-hugging-faces-ml-gui-framework/)) |

Human safety: **do not** use raw segmentation output as the sole input to physical actuators (robotics, surgery, weapons guidance) without independent validation and fail-safe design.

---

## Repository-specific risks

The following items were identified from static review of this tree. They are **documentation of current behavior**, not an assertion that each is exploitable in every deployment.

### 1. PyTorch checkpoint loading (`weights_only=False`)

`ultralytics/nn/tasks.py` loads checkpoints with:

```python
torch.load(file, map_location='cpu', weights_only=False)
```

Loading a malicious `.pt` file can execute arbitrary code during unpickling ([PyTorch security guide](https://github.com/pytorch/pytorch/security/policy), [Safeguard PyTorch guide](https://safeguard.sh/resources/blog/pytorch-security-guide)). **Mitigation:** only load checkpoints from trusted sources; verify SHA-256; prefer isolated environments for unknown weights; keep PyTorch ≥ 2.6 and use `weights_only=True` only when compatible with your checkpoint format (many legacy YOLO checkpoints require full load).

### 2. Gradio demo without authentication

`app_gradio.py` ends with `demo.launch()` — no `auth`, no `max_file_size`, no explicit bind address. Any host that can reach the port can upload images and consume GPU ([Gradio sharing guide](https://gradio.app/guides/sharing-your-app)).

**Mitigation:** `demo.launch(auth=(...))`, reverse proxy with SSO, rate limits, `max_file_size`, do **not** use `share=True` in production, run in a container with resource limits.

### 3. CLI path and prompt handling

`Inference.py` opens `args.img_path` directly and parses `box_prompt` / `point_prompt` via `ast.literal_eval` (safe vs `eval`). However, `args.model_path` and `args.output` are not validated for path traversal when exposed to untrusted users.

### 4. Dynamic evaluation in Ultralytics CLI

`ultralytics/yolo/cfg/__init__.py` may call `eval(v)` on override values from the CLI — dangerous if untrusted users can pass arbitrary CLI args on a shared host.

### 5. Dataset auto-download and dynamic code

`ultralytics/yolo/data/utils.py` can run `os.system(s)` or `exec(s, {'yaml': data})` for dataset `download` fields defined in YAML. **Never** point auto-download at untrusted YAML on a sensitive machine.

### 6. Remote model fetch

`torch_safe_load` / `attempt_download_asset` may fetch weights from the network if paths are URL-like. Restrict egress in production and pin local paths.

### 7. Dependency posture

`requirements.txt` uses **minimum versions** (e.g. `gradio==3.35.2`, `torch>=1.7.0`) — increases exposure to [OWASP A06:2021 vulnerable components](https://github.com/OWASP/top10/blob/master/osib/docs/A06_2021-Vulnerable_and_Outdated_Components.md). `setup.py` installs CLIP from **git** without hash pinning beyond a single commit.

### 8. Ultralytics HUB and telemetry

`ultralytics/hub/session.py` uses bearer tokens for API calls. Ensure `YOLO_API_KEY` and similar env vars are scoped and rotated ([OWASP Secure AI Model Ops](https://cheatsheetseries.owasp.org/cheatsheets/Secure_AI_Model_Ops_Cheat_Sheet.html)).

### 9. Image decoding attack surface

Code paths use `PIL.Image.open`, `cv2.imread`, and optional animation/multi-frame formats. Apply [Pillow security guidance](https://pillow.readthedocs.io/en/stable/handbook/security.html) (do not disable `MAX_IMAGE_PIXELS`), cap dimensions before resize, keep Pillow/OpenCV patched.

### 10. Text mode (CLIP)

`utils/tools.py` loads OpenAI CLIP at inference time. Text prompts are passed to CLIP without length or content policy — relevant for abuse and resource use, not classic injection into CLIP itself.

---

## Controls by lifecycle phase

Mapping to [NIST SP 800-218A](https://nvlpubs.nist.gov/nistpubs/SpecialPublications/NIST.SP.800-218A.pdf) and [OWASP Secure AI Model Ops](https://cheatsheetseries.owasp.org/cheatsheets/Secure_AI_Model_Ops_Cheat_Sheet.html):

### Development

- Pin dependencies with lockfiles; run [`pip-audit`](https://github.com/pypa/pip-audit) on CI
- No secrets in git; use secret managers for API keys
- Code review for `eval`/`exec`/`shell=True`/`pickle` on untrusted input
- Pre-commit hooks (see `ultralytics/.pre-commit-config.yaml`) for style, not a substitute for security tests

### Training (when using released training code)

- Provenance for SA-1B subset and custom data; sanitize labels
- Protect checkpoints at rest; sign releases ([Sigstore model-signing](https://github.com/sigstore/model-transparency))
- Separate training network from production; do not expose `torch.distributed` to WAN ([PyTorch policy](https://github.com/pytorch/pytorch/security/policy))

### Packaging

- Generate SBOM (CycloneDX) for container images; extend with [CISA/G7 AI SBOM elements](https://content.govdelivery.com/accounts/USDHSCISA/bulletins/416bd74) (model lineage, datasets, licenses)
- Scan images with Trivy/Grype ([OWASP container hardening](https://owasp.github.io/DevSecOpsGuideline/2-Process/2-3-Build/2-3-3-Container-Security/2-3-3-2-Container-Hardening/))

### Deployment

- Authentication, TLS termination, rate limits, request size caps ([SecureAI Workshop deployment guide](https://secureai.cs.luc.edu/Workshop11/Secure_Deployment_and_Operation_of_AI_Systems.html))
- Non-root containers, read-only root FS, drop capabilities ([NVIDIA Triton deployment security](https://docs.nvidia.com/deeplearning/triton-inference-server/user-guide/docs/customization_guide/deploy.html))
- Network policies: inference only from gateway; no metadata service access from pods

### Operations

- Log request metadata, not raw sensitive images (GDPR/healthcare contexts)
- Monitor GPU memory, latency, error rate; alert on abuse patterns
- Patch cadence for PyTorch, Gradio, Pillow, OpenCV, PyYAML

---

## Deployment hardening

### Local CLI (`Inference.py`)

- Run as an unprivileged user
- Validate `img_path` and `model_path` against an allowlist directory
- Reject symlink escapes outside allowed roots
- Set `ulimit` / cgroup memory for batch jobs

### Gradio (`app_gradio.py`)

Recommended pattern:

```python
import os
os.environ.setdefault("GRADIO_TEMP_DIR", "/tmp/gradio-fastsam")

demo.queue(max_size=8)
demo.launch(
    server_name="127.0.0.1",  # or "0.0.0.0" only behind a reverse proxy
    auth=(os.environ["GRADIO_USER"], os.environ["GRADIO_PASS"]),
    max_file_size="20mb",
    show_error=True,
    # share=False  # never enable share=True on machines with sensitive data
)
```

Additional items from [Gradio authentication docs](https://gradio.app/guides/sharing-your-app) and [Hugging Face Gradio 5 security review](https://huggingface.co/blog/gradio-5-security):

- Upgrade Gradio to a supported release with security fixes; test app compatibility
- Restrict `allowed_paths` / static paths; avoid exposing host filesystem
- Terminate temp files (`delete_cache` on shutdown)
- Place OAuth / enterprise SSO in front for production ([Gradio + FastAPI `auth_dependency`](https://gradio.app/guides/sharing-your-app))

### Cog / Replicate (`cog.yaml`, `predict.py`)

- Treat the Cog container as **internet-facing**; Replicate handles outer auth, but resource limits still matter
- Pin versions in `cog.yaml` (already partially pinned); rebuild on CVE notices
- `ast.literal_eval` on `box_prompt` / `point_prompt` is appropriate; keep prompts bounded in length at the platform level

### Custom REST APIs

If wrapping FastSAM:

- Validate image bytes (magic bytes, max dimensions, allowed MIME types)
- Stream uploads to disk with quotas; virus scan if policy requires
- Separate inference credentials from admin credentials
- Apply per-API-key rate limits sized for **model extraction** threat models ([OWASP AISVS C11.2](https://github.com/OWASP/AISVS/blob/main/1.0/research/chapters/C11-Adversarial-Robustness/C11-02-Membership-Inference-Model-Inversion-Mitigation.md))

---

## Supply chain and model integrity

Per [OWASP LLM05 supply chain](https://genai.owasp.org/llmrisk2023-24/llm05-supply-chain-vulnerabilities/) and [Microsoft Zero Trust ML artifacts](https://microsoft.github.io/zerotrustassessment/docs/workshop-guidance/devsecops/DS_124):

1. **Obtain weights** only from official README links (Google Drive / Baidu / project releases). Record SHA-256 after download.
2. **Do not** auto-load checkpoints from arbitrary URLs in production configs.
3. **Verify** signatures when upstream provides them; consider [OpenSSF model-signing](https://github.com/sigstore/model-transparency) for your own releases.
4. **Document** model card fields: training data (SA-1B 2%), license (Apache 2.0), known limitations.
5. **Vet** forks of `ultralytics/` vendored in-tree before merging upstream changes.

---

## Adversarial ML and privacy

Segmentation models are vulnerable to:

- **Universal adversarial perturbations** affecting mask geometry ([ICCV 2017](https://doi.org/10.1109/iccv.2017.300))
- **Stealthy attacks** that change only target classes ([arXiv:2104.01732](https://arxiv.org/abs/2104.01732))
- **Backdoor / poisoning** in training pipelines ([arXiv HTML 2603.16405](https://arxiv.org/html/2603.16405v1))

For **privacy**, exposing mask logits, per-mask confidence, and embeddings over a public API enables membership-inference-style analysis ([arXiv:2212.01082](https://arxiv.org/html/2212.01082)). Mitigations:

- Return minimal outputs (binary masks only) when possible
- Rate-limit and authenticate
- Avoid publishing fine-tuned models trained on sensitive data without DP or legal review

For safety-critical robotics (e.g. morphological / robotome integrations): treat FastSAM as **perception assistance**, not a safety instrumented system. Enforce plausibility checks, temporal consistency, and hardware e-stops.

---

## Dependency and configuration security

| Dependency | Risk | Action |
|------------|------|--------|
| `torch` / `torchvision` | RCE via pickle checkpoints | Trust model files; patch versions; see PyTorch CVE advisories |
| `gradio` | XSS, SSRF, auth bypass (historical) | Upgrade; harden launch config |
| `Pillow` | Decompression bombs, parser bugs | Stay on current stable; enforce pixel limits |
| `opencv-python` | Malformed image parsers | Patch; sandbox untrusted decode |
| `PyYAML` | Unsafe load if misused | This repo uses `yaml.safe_load` in `ultralytics/yolo/utils/__init__.py` — keep it that way ([PyYAML docs](https://pyyaml.org/wiki/PyYAMLDocumentation)) |
| `requests` | SSRF if URLs user-controlled | Block private IP ranges in download helpers |
| CLIP (git) | Supply chain | Pin commit hash (as in `setup.py`); verify OpenAI repo integrity |

Run regularly:

```bash
pip-audit -r requirements.txt
```

Enable GitHub **Dependabot** or equivalent for this repository.

---

## Incident response

1. **Contain:** disable public Gradio/Cog endpoints; rotate API keys (Ultralytics HUB, HF tokens).
2. **Assess:** determine if malicious checkpoints or poisoned images were used.
3. **Eradicate:** redeploy from known-good image digest and verified weights.
4. **Recover:** restore monitoring; review logs for extraction or SSRF patterns.
5. **Learn:** publish a security advisory via GitHub Security Advisories when appropriate ([OpenSSF maintainer guide](https://oss-vulnerability-guide.openssf.org/maintainer-guide.html)).

Update playbooks to include **AI-specific** scenarios (model tampering, training data leak, adversarial input campaigns).

---

## Security checklist

### Before exposing inference to a network

- [ ] Authentication and TLS in front of the app
- [ ] Rate limits and upload size caps
- [ ] Gradio `share=False`; explicit `server_name` binding reviewed
- [ ] Container runs as non-root with CPU/GPU/memory limits
- [ ] Model weights checksum-verified; no writable model directory
- [ ] Secrets only via environment / vault
- [ ] `pip-audit` / image scan clean for critical CVEs
- [ ] Logging excludes sensitive image content
- [ ] Incident contact and rollback documented

### Before trusting a new checkpoint

- [ ] Source documented and checksum verified
- [ ] Loaded in isolated VM/container first
- [ ] PyTorch version patched for known `torch.load` issues
- [ ] No unexpected network callbacks on load

### Before merging vendored Ultralytics changes

- [ ] Review diff for `eval`, `exec`, `shell=True`, pickle loads
- [ ] YAML loaders remain `safe_load`
- [ ] Regression test inference on sample image

---

## References

Primary guidance and standards (consult these for full detail):

1. [OWASP Secure AI Model Ops Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Secure_AI_Model_Ops_Cheat_Sheet.html)
2. [OWASP Top 10 for LLM Applications (2025)](https://genai.owasp.org/download/43299/)
3. [OWASP LLM05 – Supply Chain Vulnerabilities](https://genai.owasp.org/llmrisk2023-24/llm05-supply-chain-vulnerabilities/)
4. [OWASP A06:2021 – Vulnerable and Outdated Components](https://github.com/OWASP/top10/blob/master/osib/docs/A06_2021-Vulnerable_and_Outdated_Components.md)
5. [OWASP DevSecOps – Container Hardening](https://owasp.github.io/DevSecOpsGuideline/2-Process/2-3-Build/2-3-3-Container-Security/2-3-3-2-Container-Hardening/)
6. [OWASP AISVS – Membership Inference & Model Inversion](https://github.com/OWASP/AISVS/blob/main/1.0/research/chapters/C11-Adversarial-Robustness/C11-02-Membership-Inference-Model-Inversion-Mitigation.md)
7. [NIST AI Risk Management Framework 1.0](https://www.nist.gov/publications/artificial-intelligence-risk-management-framework-ai-rmf-10)
8. [NIST AI RMF – Secure and Resilient characteristic](https://airc.nist.gov/airmf-resources/airmf/3-sec-characteristics/)
9. [NIST SP 800-218A – SSDF for GenAI / Foundation Models](https://nvlpubs.nist.gov/nistpubs/SpecialPublications/NIST.SP.800-218A.pdf)
10. [MITRE ATLAS](https://atlas.mitre.org/)
11. [MITRE SAFE-AI Framework (PDF)](https://atlas.mitre.org/pdf-files/SAFEAI_Full_Report.pdf)
12. [OpenSSF Vulnerability Guide / SECURITY.md templates](https://oss-vulnerability-guide.openssf.org/)
13. [GitHub – Adding a security policy](https://docs.github.com/en/code-security/how-tos/report-and-fix-vulnerabilities/configure-vulnerability-reporting/add-security-policy)
14. [PyTorch – Security Policy](https://github.com/pytorch/pytorch/security/policy)
15. [Microsoft Zero Trust – AI/ML supply chain (DS_124)](https://microsoft.github.io/zerotrustassessment/docs/workshop-guidance/devsecops/DS_124)
16. [CISA / G7 – SBOM minimum elements for AI](https://content.govdelivery.com/accounts/USDHSCISA/bulletins/416bd74)
17. [Sigstore / OpenSSF model-signing](https://github.com/sigstore/model-transparency)
18. [Gradio – Sharing your app (auth, exposure)](https://gradio.app/guides/sharing-your-app)
19. [Trail of Bits – Gradio 5 audit](https://blog.trailofbits.com/2024/10/10/auditing-gradio-5-hugging-faces-ml-gui-framework/)
20. [Hugging Face – Gradio 5 security review](https://huggingface.co/blog/gradio-5-security)
21. [Pillow – Security handbook](https://pillow.readthedocs.io/en/stable/handbook/security.html)
22. [PyYAML – Documentation (safe_load)](https://pyyaml.org/wiki/PyYAMLDocumentation)
23. [pip-audit (PyPA)](https://github.com/pypa/pip-audit)
24. [SecureAI Workshop – Secure deployment of AI systems](https://secureai.cs.luc.edu/Workshop11/Secure_Deployment_and_Operation_of_AI_Systems.html)
25. [Adversarial robustness in semantic segmentation (CVPR 2018)](https://doi.org/10.1109/cvpr.2018.00099)
26. [Universal adversarial perturbations for segmentation (ICCV 2017)](https://doi.org/10.1109/iccv.2017.300)
27. [Membership inference against segmentation models (arXiv:2212.01082)](https://arxiv.org/html/2212.01082)
28. [Backdoor attacks on segmentation / SAM family (arXiv HTML 2603.16405)](https://arxiv.org/html/2603.16405v1)

---

## Maintainer notes

- Link this file from `README.md` under a **Security** section so GitHub’s Security tab and reporters can find it ([OpenSSF recommendation](https://oss-vulnerability-guide.openssf.org/maintainer-guide.html)).
- Replace the security contact placeholder once an owner email or PVR workflow exists.
- Consider renaming on disk: GitHub convention is `SECURITY.md`; `security.md` is equivalent on case-insensitive filesystems.

**License:** This document is project documentation; model and code licensing remains per [LICENSE](LICENSE) (Apache 2.0 for the upstream model).
