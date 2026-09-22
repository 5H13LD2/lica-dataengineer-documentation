# Runtime V7 Choice and Signal Retention Evaluation — 2026-08-08

## Objective

Test whether Runtime V7 extracts, corrects, and retains customer business facts
and guided-control choices across long conversations without repeating already
settled questions. The acceptance boundary is customer-visible behavior:
generated-but-hidden cards are not treated as shown, question-only mentions do
not become choices, and later corrections replace earlier values in the same
field family.

## 2026-08-09 weak-point closure addendum

The follow-up evaluation targeted defects found by adaptive conversations,
rather than replaying only fixed customer scripts:

- An explicit delivery choice now survives a later read-only installation
  lookup. Observation query scope is model context, not customer intent.
- A clear partial correction from `255/65R17` to `225 pala` persisted as
  `225/65R17` across a three-turn bounded signal probe, while vehicle, quantity,
  Bacolod City, and delivery were retained.
- An explicit deferment produced exactly: `Sige po, no worries! Update niyo
  lang po ako bukas. Ingat! 😊` It rendered no prior CTA or card again.
- A first-turn request to see price categories for `185/65R15` rendered Budget,
  Economy, Mid Range, and Premium cards. It did not render promo or product
  cards before the customer chose a tier.
- In a 150 ms Economy-then-Premium guided-action replay, the Economy response
  was suppressed as superseded. The Premium response acknowledged Premium and
  rendered four exact product price blocks plus four image cards with tracked
  product buttons. The deterministic price-list text was deliberately retained.
- Free-text selection of a visible Apollo product plus COD/delivery questions
  bound the exact product and progressed to a grounded quote. A separate mixed
  delivery-policy replay exposed the general policy reader instead of failing
  with `tool_not_exposed`.
- A failed promo-presentation attempt before catalog search no longer prevents
  a later authorized gallery. Search still establishes eligible catalog refs;
  presentation does not create commercial authority.
- A live guided-location replay rendered the `Others` card with `Outside these
  areas? Check delivery options`. Clicking the delivered token produced:
  `Dahil hindi po kasama ang area niyo sa installation options natin, pwede
  naman po natin i-check kung available ang delivery diyan. Saan po ang
  delivery address niyo?` The model offered delivery naturally, no discovery
  tool or installation surface repeated, and structured readiness remained
  `not_started` with no fulfillment/location collected because the customer
  had not confirmed delivery.
- A separate first-turn category replay used collective Gulong.ph wording,
  answered the known size/quantity context, rendered all four deterministic
  price-category cards after the text, and asked which price range to check.

These endpoint runs used locally isolated tester sessions and `return_only`.
They prove rendered payload/state behavior, not external ManyChat delivery. The
single final repository-wide Runtime V7 suite passed `1464` tests.

## Evidence layers

1. Deterministic state regressions cover typed signal precedence, corrections,
   retractions, guided-choice supersession, product-observation retention, and
   long interruption sequences.
2. The bounded signal probe uses the live extraction model but isolates state
   extraction/normalization from full response composition.
3. Adaptive endpoint conversations start with one fixed realistic message;
   every later customer reply or click is chosen by Codex from the actual
   customer-visible response and delivered controls.

The local endpoint used staging feature flags, tester storage, `return_only`
delivery, and a tester-only provider-call ceiling. It did not send messages to
ManyChat contacts.

## Varied deterministic coverage

- Tire sizes, quantities, car models, preferred/required brands, price tiers,
  location, service type, schedule, contact details, promo interest, payment
  option, payment method, bank, and installment term.
- Same-field replacements across Budget/Economy/Mid Range/Premium, province and
  city choices, Pay Now/Pay Later, payment methods, and exact product choices.
- Eight to twelve unrelated business-information interruptions after the
  original facts, including warranty, authenticity, invoice, Sunday hours,
  installation inclusions, tire protection, stock confirmation, branches, and
  delivery questions.
- Question-only mentions such as asking whether BPI works or whether an office
  is in Makati, without treating either as the customer's selected bank or
  location.
- Stale working-memory text versus the typed signal ledger.
- Product-selection evidence surviving more than the normal three-observation
  export window.

## Bounded live signal probe

Final combined artifact:

`tmp/runtime_v7_signal_retention_probe_20260808_combined/runtime_v7_signal_retention_combined_final_20260808T075322Z/signal_retention_probe.md`

The four scenarios and all 31 evaluated turns passed after correcting the
probe's location resolver and expectation normalization. The original full run
used 31 provider calls; one targeted eight-call location rerun produced the
corrected combined result. No full response-composition calls were part of this
component probe.

Representative retained state:

- Honda Civic/Yokohama: `195/65R15` corrected to `205/60R16`, Pasig corrected to
  Quezon City, Pay Now question remained transient, while Pay Later + BDO + six
  months and contact/name survived eight turns.
- Toyota Fortuner: Bridgestone changed to Michelin, promo interest was retracted,
  Makati survived a separate Carmona branch question, and email remained.
- Mitsubishi Xpander: `175R14C` changed to `185R14C`, two tires changed to four,
  delivery changed to pickup, Alabang changed to Cubao, and a GCash question did
  not become a choice until the customer selected Pay Now + GCash.
- Nissan Navara: BFGoodrich and Premium were retained, home service was retracted
  in favor of installation, a conditional BPI question stayed transient, and
  Cavite was refined to Imus, Cavite without losing schedule/contact context.

## Adaptive transcript samples

### Case 1 — product selection, qualitative interruption, and schedule

Customer:

> Hi, need 4 tires for my 2020 Honda Civic, size 215/55R16. Around 30k total
> budget, preferably quiet for daily city driving. Installation sana in Pasig.

Runtime showed the Double Warranty card, three grounded tire options, and exact
product buttons. Codex clicked the delivered BFGoodrich button.

Customer:

> Before ako pumili ng schedule, mas tahimik at comfortable ba talaga itong
> BFGoodrich kaysa doon sa Yokohama na pinakita mo? Daily city driving mostly.

The runtime initially misclassified `mostly` as a payment-month phrase and
returned a payment fallback. Word-boundary payment detection fixed this.

Customer correction:

> Hindi po payment yung tanong ko... alin mas quiet...

The runtime then compared the touring characteristics and recommended Yokohama
for the stated comfort/noise priority. Codex selected Yokohama by free text,
kept four tires and Pasig, and later requested scheduling. The runtime restored
Pasig schedule controls. Codex clicked an actual Tuesday 11:00 AM token. The
result retained Yokohama, quantity, city, partner, and slot without re-asking
product or location.

### Case 2 — promo catalog, generic Choose Brand, free-text facts, and city choice

Customer:

> Hello po, ano ang current tire promos ninyo? Naghahanap ako ng value for
> money pero wala pa akong preferred brand.

The first run lost a valid six-card promo gallery because the semantic audit
reported `decision=unsupported` while its own reason said the response was
grounded. The audit had hallucinated a category surface that was not in its
evidence packet. After requiring an actual category surface before applying
that override, the same opening returned all six promo cards and buttons.

Codex clicked the delivered `Choose Brand` button on The Gulong Double Warranty.
The click was initially converted into a synthetic statement that selected the
promo title as a product SKU. This was corrected: a generic Choose Brand action
is navigation with no brand/product selection; brand-specific Check Price or
Choose Brand actions still retain the validated brand.

Customer:

> 185/65R15 po, for 4 tires. Budget to mid-range muna; installation sana around
> Cavite pero hindi pa sure sa city.

The runtime retained the size, quantity, category intent, and province and
showed actual serviceable-city buttons. Codex clicked Imus. This path exposed a
second issue: generated product candidates were recorded as if their product
cards had been delivered even though only location cards were visible.

### Case 5 — corrected customer-visible presentation boundary

Customer:

> Need 4 tires for Nissan Kicks, 215/60R17. Economy to mid-range sana.
> Installation in Bulacan, hindi pa ako sure which city.

The visible response contained only Bulacan city buttons. Product search also
generated three candidates internally, but the corrected presentation ledger
did not classify them as delivered product cards.

Codex clicked the actual Santa Maria button.

Runtime:

> Okay, noted po yung Santa Maria, Bulacan for installation.
>
> Ngayon po, alin sa mga options na pinakita ko kanina ang gusto niyo i-check
> further or i-proceed?

The important state boundary was correct in this turn:
`product_observation=true`, `product_presentation=false`, and the readiness
packet said `3 current product candidates`, not visible cards. The remaining
language incorrectly called them previously shown. The general model contract
now explicitly states that internal candidates cannot be called shown and must
be presented/restored before asking for a choice. This last prompt change has
deterministic coverage but has not been re-run in another paid two-turn adaptive
conversation in this increment.

## General fixes made from the evidence

- Durable asserted/selected/corrected signals beat transient question-only
  candidates for the same key.
- A model-classified question-only fulfillment phrase suppresses the legacy
  alias candidate, preventing `do you deliver?` from becoming delivery choice.
- Latest guided selection wins within every choice family; payment-option
  changes clear stale bank and installment qualifiers before adding validated
  new qualifiers.
- A selected product observation is pinned during state export rather than
  being evicted by later searches.
- Payment-month detection uses word boundaries, so `mostly` is no longer parsed
  as `mos`.
- Generic promo `Choose Brand` is navigation, not product/SKU selection.
- Promo audit cannot reject a gallery based on a category-surface classification
  when no category surface exists in the evidence.
- Product presentation state is based on actual customer-visible text/cards or
  tracked product buttons, not renderer metadata for suppressed surfaces.
- The model receives the neutral facts that a guided location was validated and
  whether a trusted product exists. Sales-stage transition remains model-led;
  no post-model schedule deletion, CTA rewrite, or whole-response replacement
  was added for this path.
- Customer-visible payment labels consistently use `Pay Later`; the internal
  canonical alias remains unchanged.

## Verification status

- Long-horizon state/choice tests: passed.
- Bounded live signal probe: four scenarios, 31 evaluated turns, all passed.
- Focused offline regression batch: 456 passed and one renderer expectation
  failed because it expected suppressed product metadata to remain visible.
  After correcting that expectation and finalizing the delivered-surface
  boundary, the impacted 142-test batch passed.
- Full repository/runtime suite: intentionally not run in this increment. Run it
  once immediately before merge, after the remaining selected adaptive checks.
- External delivery: not exercised; all endpoint tests were `return_only`.

## Remaining release checks

1. One focused adaptive confirmation that a hidden product search is restored as
   visible product choices after a city click, with no “shown earlier” wording.
2. A guided price-category click path with actual delivered category controls;
   current adaptive openings were routed to the promo catalog instead.
3. One controlled endpoint delivery check, then the complete Runtime V7 test
   suite once immediately before merge.

## 2026-08-08 adaptive model-led architecture increment

The local evaluator was restarted with the main checkout's credential file and
the literal, non-secret staging router/feature configuration. It remained
`return_only`; no ManyChat customer received these messages. After each runtime
turn, Codex read the complete response and chose the next free-text reply or an
actual returned guided token as a plausible customer. Replies were not selected
from a fixed transcript.

### Quiet/budget discovery through guided location

Customer:

> Vios 2019, 4 tires, tahimik sana around 4k each.

Runtime asked for sidewall confirmation and showed candidate sizes without
calling them confirmed fitment. Codex then replied:

> Nasa sidewall po 185/60R15. Okay lang kahit konting lampas basta mas tahimik
> at matibay.

Runtime presented three grounded products with images and tracked product
buttons, plus the reviewed Double Warranty catalog card. Codex asked:

> Alin diyan ang mas tahimik at comfortable, Laufenn o Deestone? Worth it ba
> yung difference?

Runtime:

> Para sa tahimik at comfortable na gulong, mas lean po tayo sa Laufenn. Base
> sa brand profile nila, ang Laufenn ay "designed for comfort and everyday
> driving" at nasa Mid Range category.
>
> Ang Deestone naman, na gawa sa Thailand at Economy category, ay "designed for
> daily commuters and light off-road use" at may 4 years na manufacturer
> warranty.
>
> Kung priority niyo talaga ang tahimik at comfortable na ride, worth it po ang
> maliit na dagdag sa Laufenn dahil sa focus nito sa comfort at mas mahabang
> warranty.
>
> Para po ma-check natin ang installation options, saan po ang area niyo?

Codex clicked the actual Laufenn product token. Runtime retained the exact SKU,
four-tire total, and quantity wording as `4 pcs`, then rendered eight province
choices. Codex clicked the actual Metro Manila token. Runtime accepted it and
rendered fourteen serviceable-city choices with current slot previews; it did
not skip directly to a schedule choice.

### Generic assistance and business identity

Customer:

> Hi, may available ba na makaka-assist? Online lang ba kayo or may physical
> shop?

Runtime answered the requested operating-model question, explained the
installation network and warehouse-to-site flow, identified the Makati site in
the context of the physical-shop question, then asked for a tire size or car
model. Codex replied with a Honda City 2021 and Bacoor. Runtime retained Bacoor,
showed candidate sizes, and asked only for sidewall confirmation. It did not
invent fitment or prematurely render scheduling controls.

### Mixed promo, product, payment, and location

Customer:

> Hello, may promo ba ngayon for 205/55R16? Prefer ko Bridgestone pero open to
> other brands. 2 tires lang and card installment sana.

The original serving design failed this turn at the tester's eight-call ceiling:
background extraction, retrieval, main planning, final composition, separate
payment/product semantic decisions, and independent FAQ/promo audits overlapped.
This was a runtime orchestration failure, not a simulator artifact.

After removing the duplicate serving authorities, the same request completed
within the original ceiling. Runtime opened naturally, presented three grounded
205/55R16 product cards with exact two-tire prices and supported installment
rows, included the approved Double Warranty catalog card, and asked which
product to check. Codex then replied:

> Yung Bridgestone sana. BDO card gagamitin ko, and Sta. Rosa Laguna area ako.

Runtime:

> Okay, na-check na po natin yung request niyo! Para sa Bridgestone 205/55R16 na
> 2 tires, available po ang BRIDGESTONE ECOPIA EP300 91V. Puwede po ito sa BDO
> card niyo for 3-month 0% interest installment under Pay Now.
>
> May installation partners din po tayo sa Sta. Rosa City, Laguna at sa Binan,
> Laguna.
>
> Para ma-check natin ang available installation slots sa Sta. Rosa City,
> Laguna, anong araw or oras po kayo available?

This turn used product, payment-policy, and installation-partner evidence from
their providers. It retained the size, quantity, brand, BDO installment context,
and location across turns without a legacy payment-stage classifier.

### Guided-surface coverage and limits

- Product presentation: three tracked product/image choices rendered; one
  actual product token was accepted.
- Promo catalog: the reviewed Double Warranty card/image rendered as supporting
  product context. A repeated tester-only rendering on the following turn
  exposed an inclusion-visibility bookkeeping gap; the approved promo ref now
  counts as visible inclusions in return-only state as well as successful
  delivery state.
- Location: eight province choices and fourteen city choices rendered; one
  province token was accepted in this path.
- Product-specific payment: exact supported rows were included in the product
  result, so no redundant generic payment-choice surface was shown.

These probes prove local staging-parity rendering, allowlist-backed click
validation, state retention, and the model's interpretation of the selected
choice. They do not prove external ManyChat delivery. After the final authority
cleanup, 989 focused tests passed across the affected cross-surface, state,
follow-up, and renderer files. The repository-wide suite remains intentionally
deferred until the immediate pre-merge gate.
