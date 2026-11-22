"""The catalogue shows useful facts, and has real loading and empty states."""
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / 'serve' / 'web'
JS = (WEB / 'optional-catalogue.js').read_text(encoding='utf-8')
CSS = (WEB / 'catalogue.css').read_text(encoding='utf-8')


class CatalogueQualityTests(unittest.TestCase):
    def test_the_list_shows_the_licence_and_declared_context(self):
        """A model list entry must carry the facts that decide whether it is usable."""
        for marker in ('license', 'context', 'gib(', 'execution_mode'):
            with self.subTest(marker=marker):
                self.assertIn(marker, JS)

    def test_sizes_use_tabular_figures(self):
        self.assertIn('tabular-nums', CSS,
                      'model sizes must not shift while the list re-renders')

    def test_a_loading_skeleton_exists(self):
        for marker in ('catalogue-skeleton', 'aria-busy'):
            with self.subTest(marker=marker):
                self.assertTrue(marker in JS or marker in CSS,
                                f'the catalogue has no {marker}')

    def test_an_empty_state_explains_what_to_do_next(self):
        self.assertIn('Nessun modello', JS,
                      'an empty result must say what happened and what to try')

    def test_the_workspace_css_is_not_stacked_in_three_generations(self):
        """Each override block repeated the same selectors at top level; count those.

        A base rule plus one per breakpoint is normal. Three separate generations
        re-declaring the same selector outside media queries is what made the layout
        unpredictable.
        """
        top_level = re.sub(r'@media[^{]*\{(?:[^{}]|\{[^{}]*\})*\}', '', CSS)
        for selector in ('#optional-catalogue-dialog .optional-model-workspace{',
                         '#optional-catalogue-dialog .optional-model-list{',
                         '#optional-catalogue-dialog .optional-model-detail{',
                         '#optional-catalogue-dialog .catalogue-search{',
                         '#optional-catalogue-dialog .catalogue-metrics{',
                         '#optional-catalogue-dialog .optional-publication-facts{'):
            with self.subTest(selector=selector):
                occurrences = top_level.count(selector)
                self.assertLessEqual(occurrences, 1,
                                     f'{selector} is declared {occurrences} times at top level')

    def test_the_detail_pane_and_list_scroll_independently(self):
        self.assertIn('overflow:auto', CSS)
        self.assertIn('scrollbar-gutter', CSS)

    def test_entries_with_no_compatible_runtime_are_labelled(self):
        self.assertIn('runtime_supported===false', JS)

    def test_every_download_button_states_its_reason(self):
        self.assertIn('Spazio disco insufficiente', JS)
        self.assertIn('Runtime dedicato richiesto', JS)


if __name__ == '__main__':
    unittest.main()


class ToolbarLayoutTests(unittest.TestCase):
    """Controls must never overlap, whatever the text length."""

    def test_the_count_never_overlaps_the_more_button(self):
        for marker in ('#optional-catalogue-dialog .optional-catalogue-toolbar>span{',
                       '#optional-catalogue-dialog #optional-search-more{'):
            with self.subTest(marker=marker):
                self.assertIn(marker, CSS)
        rule = CSS[CSS.index('#optional-catalogue-dialog #optional-search-more{'):]
        rule = rule[:rule.index('}')]
        self.assertIn('flex:0 0 auto', rule, 'the more button must keep its own box')

    def test_the_device_filters_keep_their_own_box(self):
        rule = CSS[CSS.index('#optional-catalogue-dialog #optional-device-filters{'):]
        rule = rule[:rule.index('}')]
        self.assertIn('flex:0 0 auto', rule)

    def test_the_sort_control_cannot_overflow_its_box(self):
        self.assertIn('min-width:0', CSS[CSS.index('#optional-catalogue-dialog .optional-catalogue-toolbar .premium-select{'):].split('}')[0])

    def test_the_detail_pane_stretches_and_scrolls_inside(self):
        detail = CSS[CSS.index('#optional-catalogue-dialog .optional-model-detail{'):]
        detail = detail[:detail.index('}')]
        self.assertIn('align-self:stretch', detail)
        self.assertIn('overflow:hidden', detail)
        self.assertIn('#optional-catalogue-dialog .optional-overview,', CSS,
                      'the overview must scroll inside the pane, not push it open')


class TagColourTests(unittest.TestCase):
    """Each kind of fact has its own colour, so a list row reads at a glance."""

    def test_every_fact_kind_has_its_own_colour(self):
        for tone in ('catalogue-format', 'catalogue-size', 'catalogue-execution',
                     'catalogue-author', 'st-info'):
            with self.subTest(tone=tone):
                self.assertIn(tone, CSS)

    def test_the_context_tag_has_its_own_class(self):
        self.assertIn('optional-list-context', JS)
        self.assertIn('optional-list-context', CSS)

    def test_the_flags_do_not_share_one_colour(self):
        for selector in ('optional-list-format', 'optional-list-num',
                         'optional-list-license', 'optional-list-context'):
            with self.subTest(selector=selector):
                self.assertIn(selector, CSS)

    def test_a_warning_keeps_the_danger_colour(self):
        self.assertIn('optional-list-warning', CSS)
        self.assertIn('var(--st-danger)', CSS)
