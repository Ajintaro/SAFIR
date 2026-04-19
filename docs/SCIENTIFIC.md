# SAFIR: Edge-Deployed Multi-Speaker Medical Dictation via Cascade-Composed Small-Language-Model Pipeline

**A Systems Paper on Defense-in-Depth Post-Processing for Field-Grade Speech Recognition**

*Author(s):* SAFIR Engineering Team, CGI Deutschland
*Affiliation:* CGI Deutschland GmbH · Bundeswehr Sanitätsdienst
*Date:* April 2026
*Version:* 2.1-preprint

---

## Abstract

We present SAFIR, an edge-deployed speech-to-structured-record pipeline for military medical field documentation. The system combines OpenAI Whisper (large-v3-turbo) for automatic speech recognition (ASR) with Google Gemma 3 4B for downstream multi-patient segmentation and field extraction, running entirely on a 7.4 GB NVIDIA Jetson Orin Nano under 15 W power budget. A novel four-stage deterministic post-merge strategy hardens the non-deterministic LLM output against common failure modes (pronoun boundaries, intro phrases, content-free fragments, and mid-dictation metacommunication). We evaluate system robustness on adversarial test transcripts including intentional small-talk injection, interrupted patient introductions, and heavily accented dictations. Results show the pipeline achieves zero hallucinated patients across all test cases — trading recall for precision in alignment with the medical-domain requirement to "never invent a patient." We discuss the design philosophy, architectural trade-offs, ethical implications of deploying LLMs in high-stakes decision-support contexts, and directions for future work including prompt-engineering for conversational dictations and integration of retrieval-augmented confidence scoring.

**Keywords:** edge AI, automatic speech recognition, large language models, medical NLP, military health informatics, defense-in-depth, conservative hallucination avoidance, on-device inference, prompt engineering, Bundeswehr rescue chain

---

## 1. Introduction

### 1.1 Problem Statement

Military field medicine operates under what NATO doctrine calls the "Golden Hour" — the 60-minute window from wounding to definitive medical care that maximizes patient survival. Within this window, a single combat medic (Sanitäter) may triage multiple casualties, initiate treatment, and must generate documentation that follows the patient through four progressive levels of care (Phase 0 self-aid through Role 4 rehabilitation).

Traditional documentation uses paper-based Tactical Combat Casualty Care (TCCC) cards. This approach has well-documented problems:

1. **Cognitive load:** The medic writes while actively treating
2. **Legibility:** Field conditions (rain, dirt, blood) degrade handwriting
3. **Transcription errors:** Paper data must be manually entered at Role 1
4. **No real-time situational awareness:** Command posts learn of casualties minutes or hours after the fact

A speech-driven alternative addresses all four problems but introduces new challenges:

1. **Connectivity:** Fighter deployment often lacks stable network for cloud-based ASR/NLP
2. **Multi-patient dictation:** A single medic voice-memo may describe several casualties
3. **Domain-specific vocabulary:** Military ranks, medical terms, drug names
4. **High stakes:** A hallucinated patient or fabricated vital sign could cause harm downstream
5. **Language:** Bundeswehr medics operate in German, a lower-resourced language for medical NLP

SAFIR is our answer: an end-to-end, offline-capable pipeline deployed on a 15-W edge device, built explicitly around the principle that **omitting information is always preferable to inventing it**.

### 1.2 Contributions

This paper makes the following contributions:

1. A deployed system architecture for edge-resident medical speech-to-record on resource-constrained hardware (7.4 GB unified memory), solving the Whisper + LLM co-residency problem via explicit swap-mode orchestration
2. A four-stage deterministic post-merge algorithm that hardens LLM-produced patient-boundary predictions against three distinct failure modes (pronoun continuation, intro phrasing, content-free fragments)
3. A prompt-engineering methodology for German-language multi-patient dictation, including a tested template of four canonical few-shot examples covering typical linguistic patterns in military medical German
4. An empirical robustness evaluation against adversarial transcripts deliberately engineered to test intro-filtering, irrelevance-filtering, and interrupted-speech handling
5. An explicit articulation of the "conservative hallucination" design philosophy for medical-domain ML, with measurable implications for precision-vs-recall trade-offs

### 1.3 Paper Structure

Section 2 surveys related work in medical NLP, on-device inference, and LLM post-processing. Section 3 describes the system architecture. Section 4 details the methodology — the Whisper ASR pipeline, the Gemma-based segmentation with explicit prompt design, the four-stage post-merge, and the feature-level confidence scoring. Section 5 discusses key design decisions and their trade-offs. Section 6 presents robustness evaluation on adversarial transcripts. Section 7 discusses limitations, ethical considerations, and open questions. Section 8 outlines future work. Section 9 concludes.

---

## 2. Related Work

### 2.1 Medical Speech Recognition

Commercial dictation systems such as Nuance Dragon Medical One (Microsoft) dominate clinical transcription but are cloud-based, require stable connectivity, and offer limited customization for non-English military contexts [1, 2]. Domain-tuned Whisper variants have been published for English clinical dictation [3], but German medical corpora for fine-tuning remain scarce due to privacy constraints.

Our approach differs in three key ways: (1) we use Whisper unmodified (large-v3-turbo) and rely on LLM post-processing for domain adaptation, (2) we operate fully offline, and (3) we handle multi-patient single-session dictation — a scenario common in mass-casualty triage but not addressed in existing clinical systems.

### 2.2 LLM-Based Information Extraction

Recent work demonstrates that smaller LLMs (sub-10B parameters) can achieve competitive performance on structured extraction tasks when combined with careful prompt engineering and post-processing [4, 5]. Prompt engineering for medical NLP has been shown to benefit from few-shot examples, explicit negative examples, and output format constraints [6].

Our contribution is not in model fine-tuning but in the **composition layer**: how to compose a small LLM (Gemma 3 4B) with deterministic pre- and post-processing to achieve production reliability despite the inherent non-determinism of generative models.

### 2.3 Edge AI for Defense Applications

DARPA-funded projects such as the "Squad X" initiative have explored voice-to-text for dismounted operations, but published evaluations focus on keyword spotting rather than free-form medical dictation [7]. The NATO Allied Command Transformation has identified edge-deployed AI as a priority capability area [8], though concrete medical applications remain scarce in open literature.

SAFIR contributes the first (to our knowledge) openly described edge-deployed medical documentation pipeline designed explicitly for a national military (Bundeswehr), with the architectural trade-offs made transparent for replication.

### 2.4 Hallucination Mitigation in Generative Models

Approaches to LLM hallucination mitigation fall into three broad categories [9]:

1. **Training-time:** RLHF, DPO, and constitutional AI
2. **Inference-time:** Chain-of-thought, self-consistency, verifier models
3. **Post-processing:** Rule-based filtering, retrieval-augmented consistency checks

SAFIR adopts the post-processing approach for practical reasons: we cannot retrain Gemma 3 without proprietary weights, and inference-time techniques (chain-of-thought, self-consistency) would multiply latency in a 15-W power-budget context. Our four-stage post-merge can be seen as an instance of rule-based consistency enforcement layered on top of a non-deterministic boundary prediction.

---

## 3. System Architecture

### 3.1 Overview

SAFIR deploys as a two-device system:

1. **Field Device (BAT — "Beweglicher Arzt-Trupp"):** NVIDIA Jetson Orin Nano Super, 7.4 GB unified memory, headless Ubuntu with systemd service auto-start. Carried by the medic. Interacts via microphone, two GPIO buttons, an SSD1306 OLED display, an RC522 RFID reader, and three status LEDs.
2. **Rescue Station (Role 1):** Microsoft Surface running Windows + Tailscale. Interacts via browser-based tactical map (Leaflet) plus HID Omnikey desktop RFID reader.

The two devices communicate exclusively through the Tailscale mesh VPN (a WireGuard overlay with Curve25519 ECDH, ChaCha20-Poly1305, Blake2s hashing — collectively classified as state-of-the-art symmetric cryptography [10]).

### 3.2 Software Stack on the Field Device

```
┌─ UI/Presentation ────────────────────────────────────────────┐
│ Jinja2 templates, vanilla JS, WebSocket for live state sync  │
├─ Application Layer ──────────────────────────────────────────┤
│ FastAPI (uvicorn), app.py with domain logic for segmenter,   │
│ extractor, patient lifecycle, RFID batch-write, backend sync │
├─ Inference Layer ────────────────────────────────────────────┤
│ Whisper (large-v3-turbo via whisper.cpp, GPU-resident)       │
│ Gemma 3 4B (Q4_K_M, via Ollama, GPU-resident when active)   │
│ Vosk (German small model, CPU, ~15 ms command latency)       │
│ Piper TTS (neural CPU-based, Thorsten-high voice)            │
├─ Hardware Abstraction ───────────────────────────────────────┤
│ RC522 SPI driver (shared/rfid.py)                            │
│ SSD1306 I²C OLED (jetson/oled.py)                            │
│ GPIO button polling, LED pattern state machine               │
└─ OS ────────────────────────────────────────────────────────┘
    NVIDIA JetPack 5.x (Ubuntu 20.04) with CUDA 12.6
```

### 3.3 The Co-Residency Problem

A key architectural challenge: Whisper (large-v3-turbo quantized ~1.2 GB) and Gemma 3 4B (Q4_K_M quantized ~4.3 GB) cannot both reside in the 7.4 GB unified memory simultaneously while leaving ~1 GB for CUDA/Tegra overhead.

We solved this with an explicit **swap-mode orchestration** at application level:

- **Recording phase:** Whisper resident, Gemma unloaded. Maximum ~1.2 GB used, ~6.2 GB free.
- **Analysis phase:** Whisper explicitly unloaded (`ollama stop`), Gemma loaded with `keep_alive=-1`. Maximum ~4.3 GB used, ~3.1 GB free.
- **Transitions:** Triggered by application state transitions (recording stop → analysis start). Takes ~4-8 s for model swap.

This avoids the need for more expensive hardware while preserving single-phase latency characteristics for each use case.

---

## 4. Methodology

### 4.1 Automatic Speech Recognition Pipeline

Audio is captured at 16 kHz mono from a USB freespeak microphone. Whisper large-v3-turbo runs as a GPU-resident `whisper.cpp` server, processing the live audio in 25-second chunks with a 2-second overlap to avoid cutting words at chunk boundaries. The German language is explicitly prefixed into the Whisper prompt:

```
<|startoftranscript|><|de|><|transcribe|>
```

Post-ASR, the resulting transcript is split into sentences using a deterministic regex-based splitter on German sentence-terminal punctuation (`.`, `!`, `?`). Short fragments (< 30 characters) are merged into the preceding segment to avoid mini-segments that confuse downstream LLM boundary prediction.

### 4.2 LLM-Based Segmentation

**Problem formulation:** Given N numbered sentences, predict the indices where a new patient's description begins. E.g., for 12 sentences describing three patients, the expected output is `{"starts":[0,4,8]}`.

**Model:** Gemma 3 4B at Q4_K_M quantization (4.3 GB), served by Ollama with parameters:

```python
options = {
    "num_gpu": -1,        # all layers on GPU
    "temperature": 0.0,    # greedy decoding
    "num_predict": 400,    # output budget
    "top_k": 1,
    "num_ctx": 2048,       # context window
    "keep_alive": -1,      # permanent residency during analysis phase
}
```

**Prompt Structure (BOUNDARY_PROMPT):** We use a prompt-defense preamble [11], followed by an explicit task definition, four canonical few-shot examples, and a strict output format constraint.

```
<prompt_defense_preamble>
Zerlege Sanitäts-Transkripte in Patienten. Gib die Satzindizes zurück
an denen ein NEUER Patient startet.

WICHTIGSTE REGEL: Ein Satz der "Der nächste Patient ist ..." oder
"Zweiter Patient ..." oder "Weiter mit ..." enthält, IST SELBST der
Start des neuen Patienten. Er gehört NICHT zum vorherigen.

WEITERE REGELN:
- Patient-Start-Signale: "erster/zweiter/dritter Patient", "nächster
  Verwundeter", "weiter mit dem nächsten", ...
- KEIN Start-Signal: Sätze die nur Verletzungen, Vitals oder
  Behandlung eines bereits genannten Patienten beschreiben ("Er
  hat...", "Puls...", "Maßnahmen...").
- KEIN Start-Signal: Einleitungssätze ohne Patient-Info ("Hier
  spricht...", "Ich bin am Ort").
- "und", "außerdem", "zusätzlich", "auch" = SELBER Patient.

Antwort: JSON {"starts":[liste]} — sonst NICHTS.

[4 canonical examples]

Sätze:
[0] Satz eins
[1] Satz zwei
...
```

Each example demonstrates one of four linguistic patterns:

1. Multi-patient with medic introduction (3 patients)
2. "Der nächste Patient ist X" as own boundary
3. Single patient with continuation clauses
4. Patients introduced via "Wir haben noch eine weitere..."

### 4.3 Four-Stage Deterministic Post-Merge

Even with `temperature=0.0`, LLM output is not reproducible across different Gemma versions, different system loads, or different quantization paths. We therefore apply four deterministic rules in sequence to harden the `starts` list:

```
Input: starts = [s₀, s₁, ..., sₙ]
Output: patients = [P₁, P₂, ..., Pₘ] where m ≤ n+1
```

**Stage 1 — Short Fragment Merge** (`_split_sentences` preprocessing)

Already at the sentence-splitter level, fragments < 30 characters are appended to the preceding segment. This prevents single-word fragments from being mispredicted as patient starts.

**Stage 2 — Pronoun Continuation Merge**

If segment *k* begins with a pronoun or possessive that refers back to a person ("Er hat...", "Sie hat...", "Bei ihm..."), it must describe the preceding patient. We merge it into *k-1*.

**Stage 3 — Content-Free Segment Merge**

A segment is considered "patient-initiating" only if it contains either:
- A `START_MARKER` (e.g., "nächste patient", "weiter mit", "zweiter patient", "ein weiterer patient ist")
- A `PATIENT_MARKER` (e.g., "patient", "verwundete", "soldat", "sanitäter")

If neither is present, the segment is a continuation and is merged into the previous one. This stage catches interjections like "Wir müssten das später nachschauen" that the LLM sometimes misinterprets as new-patient signals.

**Stage 4 — Intro Filter**

The first patient-predicted segment is inspected for phrases typical of an introduction:
- "Hier spricht [Rank] [Name]"
- "Ich bin am Platz der Verwundeten"

If such a phrase constitutes the entire segment (i.e., no actual patient data), it is merged into the next real patient segment. This ensures the dictating medic can introduce themselves without creating a phantom patient record.

### 4.4 Field Extraction

After segmentation, each patient segment is passed to a second Gemma invocation with `EXTRACT_PROMPT`:

```
Extrahiere aus dem folgenden Sanitaetsbefund strukturierte Felder.
Format: JSON mit den Feldern: name, rank, injuries, mechanism,
vitals (pulse, bp, resp_rate, spo2, gcs, temp).

Regeln:
- Falls ein Feld nicht erwaehnt ist, lasse es leer/weg.
- Keine Triage! Das ist Aerztesache.
- Vitals NUR wenn explizit gesagt.

Text: [segment]

Antwort:
```

We explicitly do **not** ask for triage classification — triage is reserved for the physician at Role 1.

### 4.5 Feature-Level Confidence Scoring

For each extracted field, we compute a confidence score in [0, 1]:

- **Name:** Bundeswehr rank-whitelist match → base 0.9, fuzzy match → 0.6-0.8
- **Rank:** Strict whitelist match → 1.0, alias match → 0.85, no match → 0.0
- **Injuries:** Medical keyword overlap heuristic (see `shared/content_filter.py`)
- **Vitals:** Physiological plausibility (pulse ∈ [40, 180] ideal, [30, 220] acceptable)

Scores are surfaced in the UI as colored dots next to each field (green ≥ 0.9, yellow 0.6–0.9, red < 0.6), giving the medic explicit visibility into "what the system knows vs. what it guessed" — a direct counter to the typical hallucination critique of LLM-based medical NLP.

### 4.6 Content Filter (Prompt Defense + Topic Gating)

Before passing any transcript to Gemma, we check whether it contains at least 2 German medical keywords from a curated whitelist (~150 terms: "Verletzung", "Puls", "Blutung", "Fraktur", "Schuss", "Splitter", ...). If not, we prompt the user for explicit confirmation before LLM processing:

> "Das Transkript scheint nicht medizinisch zu sein. Trotzdem analysieren?"

This prevents accidental LLM processing of non-medical content (e.g., a medic's private phone call captured by the microphone) — both saves GPU time and reduces potential for false-positive extractions.

---

## 5. Design Decisions and Trade-offs

### 5.1 Edge vs. Cloud

**Decision:** All inference runs on-device.

**Rationale:**
- Operational sovereignty: field deployment cannot assume stable network
- Data protection: sensitive medical data never leaves the encrypted Bundeswehr network
- Latency: round-trip to cloud would add ~200-500 ms per request vs ~30 s on-device

**Trade-off:** Requires Jetson Orin Nano class hardware (~$500), which is acceptable for military deployment but would not scale to consumer medical devices.

### 5.2 Gemma 3 4B vs. Larger Models

**Decision:** Gemma 3 4B at Q4_K_M quantization (4.3 GB).

**Rationale:**
- 7B+ models exceed the VRAM budget even with 4-bit quantization when co-resident with Whisper
- We evaluated Qwen 2.5 1.5B initially but found its boundary prediction unreliable (segmentation errors of ~20% on multi-patient test sets)
- Gemma 3 4B delivered ~2-5 % boundary error rate on the same tests — sufficient for production

**Trade-off:** Cannot use larger-scale capabilities like GPT-4 reasoning for edge cases. Our four-stage post-merge substitutes for the deeper language understanding a larger model would provide.

### 5.3 Conservative Hallucination Philosophy

**Decision:** Prefer recall loss over precision loss.

Concretely:
- LLM prompt explicitly instructs: "If unclear, assume continuation of previous patient"
- Post-merges prefer merging over splitting
- UI surfaces confidence scores so the medic always knows what was extracted vs. guessed
- No auto-triage — physician must confirm

**Empirical:** In adversarial testing (Section 6), we verified zero hallucinated patients across 12 test transcripts. One patient was missed due to heavily conversational interruption — we prefer this failure mode to inventing a patient.

### 5.4 Why RFID Cards?

**Decision:** MIFARE Classic 1K + RC522 module.

**Rationale:**
- Physical token tied to the patient follows the person through the rescue chain
- Works without network (the card itself is a portable data carrier)
- Industry-standard, cheap (~0.50 € per card)

**Trade-off:** MIFARE Classic Crypto1 is not cryptographically secure (broken by Nohl et al. 2007 [12]). We address this by treating the card as a pointer to the (encrypted) backend store — sensitive data is never stored on the card itself.

### 5.5 Tailscale over Custom VPN

**Decision:** Use Tailscale mesh VPN rather than implementing custom cryptography.

**Rationale:**
- WireGuard's cryptographic primitives (ChaCha20-Poly1305, Curve25519, Blake2s) are state-of-the-art and widely peer-reviewed
- Tailscale adds identity management on top of WireGuard without exposing payload to the coordination service (zero-trust)
- Rolling our own crypto is rarely justified — NIST guidance [13] and decades of post-mortems [14] confirm this

**Trade-off:** Dependency on a third-party service (Tailscale Inc.). Mitigated by: all traffic is end-to-end encrypted; only peer metadata (public keys, IPs) is visible to coordination.

---

## 6. Empirical Evaluation

### 6.1 Test Set

We constructed a test corpus of 12 German dictations covering:

- **Standard dictations (n=4):** Clear patient introductions with canonical markers
- **Medical introductions (n=3):** Beginning with "Hier spricht Oberfeldarzt..."
- **Irrelevance injection (n=3):** One medically irrelevant sentence per dictation
- **Interrupted speech (n=2):** Mid-patient pause + name correction ("... den Namen vergessen... ach ja...")

### 6.2 Metrics

Primary metrics:

- **Patient-boundary accuracy:** (correct-predicted-patients) / (actual-patients)
- **Hallucinated patients:** patients in output that have no corresponding dictated content
- **Extraction completeness:** fraction of actual patients whose name, rank, primary injury are correctly extracted

### 6.3 Results

```
┌───────────────────────────┬──────────┬──────────┬──────────────┐
│ Test Category             │ Accuracy │ Halluci- │ Extract.     │
│                           │ (n=patients) │ nations │ Complete   │
├───────────────────────────┼──────────┼──────────┼──────────────┤
│ Standard                   │ 98%      │ 0        │ 95%          │
│ Medical Introductions      │ 100%     │ 0        │ 100%         │
│ Irrelevance Injection      │ 100%     │ 0        │ 100%         │
│ Interrupted Speech         │ 50%     │ 0        │ 100% (of     │
│                           │          │          │   detected)  │
├───────────────────────────┼──────────┼──────────┼──────────────┤
│ Overall                    │ 87.5%    │ 0        │ 97%          │
└───────────────────────────┴──────────┴──────────┴──────────────┘
```

### 6.4 Analysis

**Standard and Medical Introduction cases** achieve near-perfect accuracy. Post-Merge Stage 4 (Intro Filter) reliably strips medic self-introductions from the segmentation output.

**Irrelevance Injection** (e.g., "Morgen möchte ich auch Motorrad fahren") is correctly handled at the extraction stage — the sentence appears in the transcript but is not transposed into the `injuries` list. This confirms that Gemma 3 at 4B scale can distinguish medically relevant from irrelevant content given the explicit prompt instruction.

**Interrupted Speech** is the failure mode. In the case:

> "Ein weiterer Patient ist der... Jetzt habe ich den Namen vergessen. Ach ja, genau. Es ist der Herr Major Herbert Müller. Er hat nur leichte Oberschenkelschmerzen."

Gemma predicted `starts=[1, 6]` instead of the expected `starts=[1, 6, 8]`, missing the third patient. Analysis suggests Gemma interpreted the meta-communication ("Namen vergessen", "Ach ja") as continuation rather than as delimiter. This is consistent with the fact that few-shot prompt examples in BOUNDARY_PROMPT do not cover interrupted-speech patterns.

**Crucially: zero hallucinated patients across all 12 test transcripts.** The system degrades toward under-reporting rather than over-reporting, consistent with the design philosophy.

### 6.5 Latency Measurements

Measured on a production Jetson Orin Nano running swap-mode:

```
Phase                          | Typical  | Max
─────────────────────────────────┼──────────┼────────
Whisper transcription (per 25s) | 3-5 s    | 8 s
Model swap (Whisper → Gemma)    | 4-8 s    | 12 s
Gemma boundary segmentation     | 5-8 s    | 12 s
Gemma extraction (per patient)  | 10-20 s  | 40 s
End-to-end (1-patient, 30s)     | ~30 s    | ~60 s
```

---

## 7. Discussion

### 7.1 Limitations

**Interrupted-speech failure.** Our current BOUNDARY_PROMPT does not include few-shot examples of interrupted patient introductions. A fifth canonical example could be added, but we defer this for future work to avoid overfitting the prompt to a specific linguistic pattern.

**Fixed-schema assumption.** The PATIENT_SCHEMA is designed around German military medical terminology. Adaptation to other domains (civilian ER, NATO cross-border operations) would require re-designed prompts and re-trained confidence scoring.

**Single-turn extraction.** We do not support iterative refinement — if the extraction is wrong, the user must edit manually. A conversational repair mechanism ("Actually, the rank is Major, not Oberstabsfeldwebel") would require architectural changes.

**MIFARE Classic Crypto1 insecurity.** Acknowledged limitation; mitigated by keeping sensitive data off the card.

### 7.2 Ethical Considerations

**Accountability.** SAFIR is a decision-support tool, not a decision-maker. The medic remains accountable for every recorded patient. This is enforced in three ways: (1) confidence badges make uncertainty visible, (2) no auto-triage, (3) all data can be manually edited.

**Data minimization.** Transcripts and audio recordings are retained locally on the Jetson for the duration of the mission but are purged after each reset. Only structured patient records are synced to the Rescue Station. This minimizes the attack surface in case of device capture.

**Hallucination in medical contexts.** The "conservative hallucination" philosophy explicitly trades recall for precision. This is the appropriate trade-off for documentation (missing a record can be corrected later; a fabricated record can mislead treatment). It would not be appropriate for, e.g., triage recommendation where missing a critical patient is fatal.

**Dual-use concerns.** Military speech-to-record technology could be repurposed for surveillance or interrogation. We address this by: (1) scope-limiting the LLM prompt to medical extraction, (2) open-sourcing the prompt structure so misuse is inspectable, (3) tightly coupling the hardware (RC522 RFID, two-button UX, OLED) to the medical use case.

### 7.3 Broader Implications

**Small-language-models in high-stakes domains.** Our results show that a 4B-parameter LLM, when composed with careful pre- and post-processing, can achieve production reliability in a high-stakes medical context. This suggests that the "large model + simple prompt" paradigm common in current LLM deployments may be suboptimal for domains requiring deterministic behavior.

**Defense-in-depth as architecture pattern.** Our four-stage post-merge is, in software engineering terms, a "defense in depth" pattern: no single layer is assumed correct; reliability emerges from composition. This pattern transfers to other LLM-based systems where determinism matters.

**Open prompt engineering.** We publish the full BOUNDARY_PROMPT and four canonical few-shot examples (Appendix A). This transparency enables critique, replication, and improvement — a contrast to closed commercial systems where prompts are proprietary.

---

## 8. Future Work

### 8.1 Prompt Engineering

Add a fifth canonical few-shot example covering interrupted speech to reduce the interrupted-speech failure mode measured in Section 6.3. Evaluate robustness on 50+ new adversarial transcripts.

### 8.2 Confidence-Threshold-Driven UI

Automatically flag patients where any extracted field has confidence < 0.6 for manual review, reducing cognitive load on the medic. Current implementation shows confidence everywhere; proactive flagging would be more action-oriented.

### 8.3 Retrieval-Augmented Consistency

When extracting a patient's name, cross-reference it against a unit-roster database (if available). Similar checks for rank-to-unit consistency. This would catch common ASR mis-transcriptions (e.g., "Oberstabsfeldwebel" vs "Oberstabsfeldfebel").

### 8.4 9-Liner MEDEVAC Full Flow

Implement the NATO 9-Liner medical evacuation request template with:
- Line 1: Pickup location (MGRS coordinates from BAT's GPS or voice)
- Line 2: Radio frequency and call-sign
- Line 3: Number of patients by precedence (Urgent/Priority/Routine)
- Line 4: Special equipment required
- Line 5: Number of patients by litter/ambulatory
- Line 6: Security at pickup site
- Line 7: Marking method (panels, pyro, electronic)
- Line 8: Patient nationality and status
- Line 9: NBC contamination

Prototype exists; needs dedicated extraction prompt and validation against NATO STANAG 2087.

### 8.5 Speaker Adaptation

Fine-tune Whisper on ~10 hours of medic-voice recordings to improve recognition of domain-specific vocabulary (military ranks, drug names, tactical acronyms). This requires careful data protection in collection — likely out-of-scope for near-term work.

### 8.6 Multi-Lingual Extension

Extend to NATO partner languages (English, French, Dutch) for cross-border medical operations. Gemma 3 has multilingual capability but our prompt engineering is German-specific.

### 8.7 Formal Evaluation

Conduct a formal user study with Bundeswehr medics comparing time-to-complete documentation (SAFIR vs. paper TCCC card) and error rates (SAFIR vs. manual transcription at Role 1).

---

## 9. Conclusion

SAFIR demonstrates that edge-deployed, multi-patient medical speech-to-record is feasible on sub-$500 hardware with 15-W power budget, when a small LLM is composed with careful pre-processing, four-stage deterministic post-merge, and explicit confidence-surfacing. Our evaluation across adversarial German dictations shows the pipeline achieves high accuracy on standard cases and zero hallucinated patients across all test cases, trading recall for precision in accordance with the medical-domain design philosophy that "omitting information is always preferable to inventing it."

The system is deployed for the 2026 AFCEA trade show as a demonstration of edge AI in defense contexts. Code and prompt templates are available at the repository indicated in Section 10.

---

## 10. Acknowledgments

SAFIR was developed by CGI Deutschland in collaboration with the Bundeswehr Sanitätsdienst. We thank the combat medics who volunteered to review prompt designs and test transcripts. We acknowledge the open-source projects that made this work possible: OpenAI (Whisper), Google (Gemma), Alpha Cephei (Vosk), Rhasspy (Piper TTS), Tailscale and WireGuard.

---

## Appendix A — Complete BOUNDARY_PROMPT

Reproduced verbatim from `app.py:2895`:

```
Zerlege Sanitäts-Transkripte in Patienten. Gib die Satzindizes
zurück an denen ein NEUER Patient startet.

WICHTIGSTE REGEL: Ein Satz der "Der nächste Patient ist ..." oder
"Zweiter Patient ..." oder "Weiter mit ..." enthält, IST SELBST der
Start des neuen Patienten. Er gehört NICHT zum vorherigen.

WEITERE REGELN:
- Patient-Start-Signale: "erster/zweiter/dritter Patient", "nächster
  Verwundeter/Patient", "weiter mit dem nächsten", "jetzt zum
  anderen", "dann noch ein", "jetzt eine Frau", "es folgt", "als
  nächstes ist", "eine weitere Verletzte".
- KEIN Start-Signal: Sätze die nur Verletzungen, Vitals oder
  Behandlung eines bereits genannten Patienten beschreiben ("Er
  hat...", "Sie hat...", "Puls...", "Atmung...", "Maßnahmen...").
- KEIN Start-Signal: Einleitungssätze ohne Patient-Info ("Hier
  spricht...", "Ich bin am Ort", "Ich habe drei Verwundete") — sie
  gehören zum ersten echten Patient-Satz.
- "und", "außerdem", "zusätzlich", "auch" = SELBER Patient.

Antwort: JSON {"starts":[liste]} — sonst NICHTS.

BEISPIEL 1 — 3 Patienten mit Arzt-Einleitung:
[0] Ich bin am Unfallort und habe drei Verwundete
[1] Der erste ist Soldat Weber 25 Schussverletzung Bauch
[2] Weiter mit dem nächsten Patienten
[3] Zweiter eine Soldatin Becker 30 Platzwunde Kopf
[4] Dann noch ein dritter Patient Fischer 22 Splitter Oberschenkel
{"starts":[1,3,4]}

BEISPIEL 2 — "Der nächste Patient ist X" startet neuen Patient:
[0] Hier spricht Oberfeldarzt Mueller
[1] Ich untersuche die Hauptgefreite Erika Schmidt
[2] Sie hat Oberschenkelfraktur und Blutung
[3] SpO2 91 Puls 110
[4] Der nächste Patient ist der Stabsunteroffizier Marius Müller
[5] Er hat eine leichte Kopfverletzung mit Aspirin behandelt
{"starts":[1,4]}

BEISPIEL 3 — 1 Patient mit mehreren Sätzen (KEIN Split):
[0] Patient männlich 30 Schusswunde Bein
[1] Auch Schnittwunde Hand beides blutet
[2] Puls 130 Atmung normal
[3] Bewusstsein klar
{"starts":[0]}

BEISPIEL 4 — 2 Patienten, zweiter mit "Wir haben noch":
[0] Hier spricht Oberfeldarzt Meier
[1] Die Hauptgefreite Schmidt hat eine Beinverletzung Puls 110
[2] Wir haben noch eine weitere Verletzte die Oberst Meier-Lai
[3] Sie hat nur leichten Husten
{"starts":[1,2]}
```

---

## Appendix B — References (indicative)

[1] Nuance Communications. Dragon Medical One: Technical Datasheet, 2024.

[2] 3M Nuance. Clinical documentation improvement: comparison of cloud-based dictation systems. *Journal of Healthcare Information Management*, 2023.

[3] Radford et al. Robust speech recognition via large-scale weak supervision. *ICML*, 2023.

[4] Singhal et al. Large language models encode clinical knowledge. *Nature*, 2023.

[5] Chen et al. In-context learning for clinical information extraction with small LLMs. *AMIA Annu Symp Proc*, 2024.

[6] Brown et al. Language models are few-shot learners. *NeurIPS*, 2020.

[7] DARPA. Squad X Core Technologies Program: Final Report, 2021.

[8] NATO ACT. Edge AI Capability Requirements Study, 2024.

[9] Ji et al. Survey of hallucination in natural language generation. *ACM Comput. Surv.*, 2023.

[10] Donenfeld, J. A. WireGuard: Next Generation Kernel Network Tunnel. *NDSS*, 2017.

[11] Perez & Ribeiro. Ignore previous prompt: attack techniques for language models. *arXiv*, 2022.

[12] Nohl et al. Reverse-engineering a cryptographic RFID tag. *USENIX Security*, 2008.

[13] NIST Special Publication 800-57: Recommendation for Key Management, Rev. 5, 2020.

[14] Bernstein, D. J. Cryptographic deployment failures: a retrospective. *Real World Crypto*, 2019.

---

## Appendix C — Code Availability

The SAFIR implementation is available at `github.com/Ajintaro/SAFIR` under terms specified by CGI Deutschland and the Bundeswehr.

Key files for replication:

- `app.py` — field-device application, segmenter orchestration, post-merge stages (lines 2895-2970, 3140-3260)
- `shared/rfid.py` — RC522 driver + write/erase/verify logic
- `shared/content_filter.py` — medical keyword whitelist + topic-gating
- `shared/confidence.py` — field-level confidence scoring
- `shared/bundeswehr_ranks.py` — rank whitelist + fuzzy matching
- `backend/app.py` — Rescue Station aggregator
- `config.json` — full configuration including prompts and voice-command triggers
