# UI/UX Readiness Checklist (ARTEMIS)

## Global states
- [ ] On first app load, a clear global loading state is visible until initial `/data/*` responses are ready.
- [ ] Simulate `/data/*` failure and confirm a global error state appears with readable recovery guidance.
- [ ] From global data load error state, `Retry` triggers a new request and restores normal UI on success.

## Map and list sync
- [ ] Select an item in the list and confirm the same object is highlighted/selected on the map.
- [ ] Select an item on the map and confirm the same object is highlighted/selected in the list.
- [ ] Hover an item in the list and confirm linked map marker/shape gets hover emphasis.
- [ ] Hover a map marker/shape and confirm linked list row gets hover emphasis.

## Detail view
- [ ] Open detail-view from list and map entry points; target object data is consistent in both flows.
- [ ] Close detail-view (close button + outside/back action where applicable) and confirm focus/context returns correctly.
- [ ] With missing optional fields, detail-view hides empty sections/placeholders (no blank content blocks).

## UGC
- [ ] UGC loading state is visible during fetch and removed after completion.
- [ ] UGC error state is explicit and does not break surrounding layout.
- [ ] UGC empty state appears when no entries exist and includes clear next-step copy.
- [ ] UGC status labels are shown consistently across list/detail contexts.

## Moderation UI
- [ ] Moderation badges use consistent labels/colors for identical statuses in all UI contexts.
- [ ] Moderation metadata (status, timestamps, actor where available) is formatted consistently.
- [ ] Moderation action controls are consistent in naming, placement, and state behavior.

## Visual consistency
- [ ] Buttons of same role (primary/secondary/ghost/danger) look and behave consistently across screens.
- [ ] Badges/chips for statuses use consistent token mapping (color, text contrast, shape).
- [ ] Core UI states (default/hover/active/disabled/error) are visually coherent across map, list, and detail-view.

## Known gaps
- [ ] Navigation / IA formalization is still partial and needs one unified UX pass.
- [ ] Design system depth is limited (tokens/components coverage needs broader normalization).
- [ ] Search/filter UX refinement remains needed for clearer intent, feedback, and edge states.
- [ ] Full-product state consistency beyond current UI/UX block still requires wider alignment.
