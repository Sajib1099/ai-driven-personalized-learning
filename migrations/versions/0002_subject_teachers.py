"""Subject-wise teacher assignments: add teacher_assignments.subject_id

Revision ID: 0002_subject_teachers
Revises: 69f264d121ed
"""
from alembic import op
import sqlalchemy as sa

revision = "0002_subject_teachers"
down_revision = "69f264d121ed"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("teacher_assignments", recreate="auto") as batch_op:
        batch_op.add_column(sa.Column("subject_id", sa.Integer(), nullable=True))
        batch_op.create_foreign_key("fk_teacher_assignments_subject_id", "subjects", ["subject_id"], ["id"],
                                    ondelete="CASCADE")
        batch_op.create_index("ix_teacher_assignments_subject_id", ["subject_id"])
        batch_op.drop_constraint("ck_assignment_target", type_="check")
        batch_op.create_check_constraint(
            "ck_assignment_target_v2", "student_id IS NOT NULL OR course_id IS NOT NULL OR subject_id IS NOT NULL")
        batch_op.create_unique_constraint("uq_teacher_subject", ["teacher_id", "subject_id"])


def downgrade() -> None:
    with op.batch_alter_table("teacher_assignments", recreate="auto") as batch_op:
        batch_op.drop_constraint("uq_teacher_subject", type_="unique")
        batch_op.drop_constraint("ck_assignment_target_v2", type_="check")
        batch_op.create_check_constraint("ck_assignment_target", "student_id IS NOT NULL OR course_id IS NOT NULL")
        batch_op.drop_index("ix_teacher_assignments_subject_id")
        batch_op.drop_constraint("fk_teacher_assignments_subject_id", type_="foreignkey")
        batch_op.drop_column("subject_id")
