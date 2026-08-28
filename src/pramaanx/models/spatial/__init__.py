"""Leakage-safe spatial baselines, count models and the classical ladder."""

from pramaanx.models.spatial.artifacts import (
    ArtifactExistsError,
    ModelArtifact,
    write_artifact,
)
from pramaanx.models.spatial.baselines import (
    DistrictHistoricalRateModel,
    RecencyCountBaseline,
    UniformBaseRateModel,
)
from pramaanx.models.spatial.contracts import (
    ContractViolationError,
    ReportingDelayPolicy,
    SpatialTrainingRow,
    TrainingRowSet,
    build_training_rows,
)
from pramaanx.models.spatial.count_models import (
    FitResult,
    FitStatus,
    HurdleRegression,
    NegativeBinomialRegression,
    PoissonRegression,
    ZeroInflatedNegativeBinomialRegression,
)
from pramaanx.models.spatial.dataset import SpatialDataset, SpatialFeatureRow
from pramaanx.models.spatial.distributions import (
    CountDistribution,
    CountFamily,
    DistributionValidationError,
)
from pramaanx.models.spatial.feature_registry import (
    FeatureRegistry,
    FeatureSpec,
    default_feature_registry,
)
from pramaanx.models.spatial.features import (
    build_extended_spatial_features,
    build_spatial_features,
)
from pramaanx.models.spatial.oof import OofLeakageError, OofRecord, build_oof_records
from pramaanx.models.spatial.prediction import (
    BASELINE_LADDER,
    FallbackLevel,
    RateHierarchy,
    SpatialPrediction,
    build_ladder,
)
from pramaanx.models.spatial.splits import (
    Fold,
    SealedSplitError,
    SplitPlan,
    SplitPolicy,
    SplitPurpose,
    build_rolling_origin_plan,
    select_rows,
)
from pramaanx.models.spatial.statistical import (
    GradientBoostedSpatialModel,
    LogisticSpatialModel,
    PoissonCountModel,
)
from pramaanx.models.spatial.training import (
    TrainingPlan,
    TrainingResult,
    plan_training,
    train_ladder,
)

__all__ = [
    "BASELINE_LADDER",
    "ArtifactExistsError",
    "ContractViolationError",
    "CountDistribution",
    "CountFamily",
    "DistributionValidationError",
    "DistrictHistoricalRateModel",
    "FallbackLevel",
    "FeatureRegistry",
    "FeatureSpec",
    "FitResult",
    "FitStatus",
    "Fold",
    "GradientBoostedSpatialModel",
    "HurdleRegression",
    "LogisticSpatialModel",
    "ModelArtifact",
    "NegativeBinomialRegression",
    "OofLeakageError",
    "OofRecord",
    "PoissonCountModel",
    "PoissonRegression",
    "RateHierarchy",
    "RecencyCountBaseline",
    "ReportingDelayPolicy",
    "SealedSplitError",
    "SpatialDataset",
    "SpatialFeatureRow",
    "SpatialPrediction",
    "SpatialTrainingRow",
    "SplitPlan",
    "SplitPolicy",
    "SplitPurpose",
    "TrainingPlan",
    "TrainingResult",
    "TrainingRowSet",
    "UniformBaseRateModel",
    "ZeroInflatedNegativeBinomialRegression",
    "build_extended_spatial_features",
    "build_ladder",
    "build_oof_records",
    "build_rolling_origin_plan",
    "build_spatial_features",
    "build_training_rows",
    "default_feature_registry",
    "plan_training",
    "select_rows",
    "train_ladder",
    "write_artifact",
]
