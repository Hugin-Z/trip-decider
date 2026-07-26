# `trip-card.html` structural delivery contract

Contract version: `0.1.0`

WU1 freezes only the delivery boundary. It does not create HTML, CSS, a
template, a renderer, or a browser-facing product.

A future single-file `trip-card.html` must expose:

- artifact metadata and references to the validated machine artifacts;
- the four-state plan status and any explicit conditions;
- evidence trace-back for displayed high-support facts;
- base selection, day, activity, and leg sections;
- excluded candidates and their reasons;
- a deterministic plan-diff summary when replanning occurred.

The file must remain usable as a single local HTML document. Rendering,
accessibility, layout, content quality, and real-trip correctness are deferred
to WU7 and WU8. Passing WU1 schemas must never be described as proof that this
HTML exists or that an itinerary is feasible.
