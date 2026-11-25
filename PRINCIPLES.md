# Design principles

**What Cascade is saying.** A person's health record is scattered across institutions that each hold a slice of it, in formats that do not agree. Cascade puts that person, the patient, at the centre: the whole record can be held in one place as plain files, controlled by the patient or by someone acting for them. Nothing anyone said is rewritten, every statement traces to who made it, and any app or model reads it the same way. It works like the Rosetta stone, which set one message side by side in languages people already used and invented none. The pod records; whoever reads it does the reasoning.

## 1. Put the patient first
A pod is built around one patient and exists to serve that patient's needs. Those needs come before the app builder's, the runtime implementer's, the vocabulary authors' and tidy design. Whoever runs the pod, whether the patient, a parent or a paid caregiver, acts on the patient's behalf. That person can see what is in the pod and decide what counts, what leaves and what is removed, and the record says who acted.

*Example:* rule Y3 of [`runtime/consent.feature`](runtime/consent.feature): a write a model proposed names the model, in `cascade:ModelProposerRole`, and the person who said yes, in `cascade:PatientRole`.

- Does this serve the patient's needs, or someone else's?
- Can whoever acts for the patient see it, overrule it and take it out?
- Does the record show who acted and in what role?
- Does anything leave the pod that nobody acting for the patient chose to send?

## 2. Translate, don't replace
Take what sources already send, in the standards they already use. Add only what is needed to relate one source to another. Ask nothing new of a hospital, a lab or a device maker. The original document is always kept whole, so nothing a source sent is lost by leaving it untranslated.

*Example:* [`runtime/pod-layout.ttl`](runtime/pod-layout.ttl) files each document a source sent under `provenance/documents/`, apart from the records made from it.

- Does this need a source to change anything it does today?
- Does it restate, in our own words, something a standard already says?
- Would someone who knows FHIR recognise this without a guide?

## 3. Reuse before you invent
Before adding a term, look for one that already says it: first in a standard, then in our own vocabulary. Add a new one only with a written "looked here, and it failed because".

*Example:* `cascade:AuthorRole` is a term of ours because HL7's provenance participant type "author", which it names with `rdfs:seeAlso`, defines a code and no concept IRI, as its comment says.

- Which existing terms were considered, and why did each fail?
- Is this a new kind of thing, or an existing kind said by a new speaker?
- Does this add a special case where a general pattern already covers it?

## 4. Record what was said and who said it, and no more
A pod holds claims and observations from many sources, each with its maker. Where two sources disagree, both stay. The pod never states a date, a precision, an absence or a certainty no source gave. Medical knowledge and clinical judgment belong to whoever reads the pod. This governs what is stored. A view may compute a date or a grouping from what is stored, and what it computes is never written back as something a source said.

*Example:* `cascade:ValueAbsentForReason` is written only where a source said why a value is missing; a value left out with no reason gets nothing, since a missing triple says nothing was said.

- If two sources disagree, does this keep both, each with its maker?
- Could this make the pod say something no source said, or hide that it does not know?
- Does this need the protocol to know medicine or to pick a winner?

## 5. Make everything traceable and undoable
For anything in a pod or shown from it, someone can find out where it came from, who made it, what it rests on, and why something else was left out. Plenty may happen without asking the person. Nothing happens without a trace, and a wrong step can be found and reversed. Removing something is the one step that cannot be reversed: it leaves a record that something was removed and by whom, without the content.

*Example:* the question [`record/Why it is in no view`](queries/questions/record/Why%20it%20is%20in%20no%20view.rq) gives, for a record no view shows, each `cascade:leftOutReason` and the thing it rests on.

- Six months on, can someone answer "why does it say this?" and "why is that not here?"
- When this goes wrong, how does anyone find out, and how do they undo it?
- If unsure, does this choose the mistake that can be reversed?

## 6. Same files, same answers, for anyone
A pod is plain files in open formats. Any implementation reading them gets the same answers, anyone can check that with ordinary tools, and the pod stays usable if our software disappears. Where an answer needs outside knowledge, such as which drugs share an ingredient, it comes from a versioned table the pod names: same files, same tables, same answers.

*Example:* `cascade:defaultTableVersion` is the version of a reference table a runtime uses until the pod names another as current, and the question [`pod/Which reference versions are current`](queries/questions/pod/Which%20reference%20versions%20are%20current.rq) asks which versions are current.

- Could a second team build this from the written rules alone and get the same result?
- If our software vanished tomorrow, could the person still open and use their pod?
- Does the answer depend on anything that is not in the files or in a table the pod names?

## 7. Say it plainly
Each term means one thing, and its name says what the thing is to a clinician, a developer or a model reading it cold. Where people mean two things there are two terms. Where the meaning is the same across kinds of record there is one term, not a copy per kind. Complicated things are said by combining simple terms.

*Example:* `cascade:narrativeText` is the one property for the text a source wrote for a record of any kind; a note a person added to a record means something else, so it is `cascade:addedNoteText`.

- Read alone in a query, does the name tell you what you have?
- Could a clinician and a developer use this word in conversation without either translating?
- Does the name carry anything that might change, such as who owns it or where it is filed?

## 8. Structure has to earn its place
Add a term, a rule or a field when a real question is answered better with it than from the raw documents. A term is added only when something reads it. Until then, leave it out and say that it was left out.

*Example:* `cascade:narrativeTextAsTrimmedLines` exists because the matcher's note rules, such as [`queries/matcher/same-note-type-and-text.rq`](queries/matcher/same-note-type-and-text.rq), compare it.

- What question does a person or a model answer better because this exists?
- Is there a present, named need, or a presumed one?
- Does it make the existing terms harder to understand?

## When two pull apart
These are rules of thumb to be balanced, not absolutes. When two pull apart, the order is: the patient (1); the honesty of the record (4, 5); anyone being able to read and check it (6); economy of the vocabulary (2, 3, 7, 8); last, our own convenience and tidy design for its own sake.

## Every rule answers to these
A rule is a sentence someone could cite to stop a change, wherever it is written: a feature file, a shape, a test, a kit's expected answers, the scenario, CLAUDE.md. Before a rule is treated as a constraint, say which principle it serves. If it serves none, it is a choice, and it can change: change it, say so in the pull request, and do not stop to ask. Old reasoning is not a constraint; nobody has checked it.

## A guideline for now, not a principle
The better design wins over what is already built. Rewriting adapters, the runtime and the test kits is a cost and never a reason against a better design. This flips at the first alpha release: from then a published name stays and a change must leave existing pods readable.
