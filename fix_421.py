# desloppify/app/cli_support/parser.py

import argparse
from desloppify.app.cli_support.parser_groups import add_common_arguments
from desloppify.app.cli_support.parser_groups_admin import add_admin_arguments
from desloppify.app.cli_support.parser_groups_admin_review import add_admin_review_arguments
from desloppify.app.cli_support.parser_groups_admin_review_options_batch import add_admin_review_options_batch_arguments
from desloppify.app.cli_support.parser_groups_admin_review_options_core import add_admin_review_options_core_arguments
from desloppify.app.cli_support.parser_groups_admin_review_options_external import add_admin_review_options_external_arguments
from desloppify.app.cli_support.parser_groups_admin_review_options_trust_post import add_admin_review_options_trust_post_arguments
from desloppify.app.cli_support.parser_groups_plan_impl import add_plan_impl_arguments
from desloppify.app.cli_support.parser_groups_plan_impl_sections_annotations import add_plan_impl_sections_annotations_arguments
from desloppify.app.cli_support.parser_groups_plan_impl_sections_cluster import add_plan_impl_sections_cluster_arguments

def create_parser():
    parser = argparse.ArgumentParser(description="Desloppify CLI Tool")
    add_common_arguments(parser)
    add_admin_arguments(parser)
    add_admin_review_arguments(parser)
    add_admin_review_options_batch_arguments(parser)
    add_admin_review_options_core_arguments(parser)
    add_admin_review_options_external_arguments(parser)
    add_admin_review_options_trust_post_arguments(parser)
    add_plan_impl_arguments(parser)
    add_plan_impl_sections_annotations_arguments(parser)
    add_plan_impl_sections_cluster_arguments(parser)
    return parser

if __name__ == "__main__":
    parser = create_parser()
    args = parser.parse_args()
    # Further processing based on args