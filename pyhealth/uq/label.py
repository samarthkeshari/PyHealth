"""
LABEL: Least ambiguous set-valued classifiers with bounded error levels.

From:
    Sadinle, Mauricio, Jing Lei, and Larry Wasserman. 
    "Least ambiguous set-valued classifiers with bounded error levels." 
    Journal of the American Statistical Association 114, no. 525 (2019): 223-234.

"""

from typing import Dict, Union

import numpy as np
import torch

from pyhealth.models import BaseModel
from pyhealth.uq.base_classes import SetPredictor
from pyhealth.uq.utils import prepare_numpy_dataset

__all__ = ['LABEL']

def _query_quantile(scores, alpha):
    scores = np.sort(scores)
    N = len(scores)
    loc = int(np.floor(alpha * (N+1))) - 1
    return -np.inf if loc == -1 else scores[loc]

class LABEL(SetPredictor):
    """LABEL: Least ambiguous set-valued classifiers with bounded error levels.
    
    This is a prediction-set constructor for multi-class classification problems.
    It controls either P{Y in C(X) | Y = k}  for each class k, or P{Y in C(X)} overall.
    Here, C(X) denotes the final prediction set.
    This is essentially a split conformal prediction method using the predicted scores.

    Paper: Sadinle, Mauricio, Jing Lei, and Larry Wasserman. 
        "Least ambiguous set-valued classifiers with bounded error levels." 
        Journal of the American Statistical Association 114, no. 525 (2019): 223-234.

    Args:
        model (BaseModel): A trained model.
        alpha (Union[float, np.ndarray]): Target mis-coverage rate(s).
            If alpha is a float (say 0.1), the guarantee is:
                P{Y not in C(X)} <= alpha
            If alpha is an array (say `np.asarray([0.1] * 5)`), the guarantee is:
                P{Y not in C(X) | Y = k} <= alpha[k]
    Examples:
        >>> from pyhealth.models import SparcNet
        >>> from pyhealth.tasks import sleep_staging_isruc_fn
        >>> sleep_ds = ISRUCDataset("/srv/scratch1/data/ISRUC-I").set_task(sleep_staging_isruc_fn)
        >>> train_data, val_data, test_data = split_by_patient(sleep_ds, [0.6, 0.2, 0.2])
        >>> model = SparcNet(dataset=sleep_staging_ds, feature_keys=["signal"],
        ...     label_key="label", mode="multiclass")
        >>> # ... Train the model here ...
        >>> # Calibrate the set classifier, with target coverage of 0.9 for each class
        >>> cal_model = uq.LABEL(model, [0.1] * 5)
        >>> cal_model.calibrate(cal_dataset=val_data)
        >>> # Evaluate
        >>> from pyhealth.trainer import Trainer
        >>> test_dl = get_dataloader(test_data, batch_size=32, shuffle=False)
        >>> print(Trainer(model=cal_model).evaluate(test_dl))
    """
    def __init__(self, model:BaseModel, alpha: Union[float, np.ndarray],
                 debug=False, **kwargs) -> None:
        super().__init__(model, **kwargs)
        if model.mode != 'multiclass':
            raise NotImplementedError()
        self.mode = self.model.mode # multiclass
        for param in model.parameters():
            param.requires_grad = False
        self.model.eval()
        self.device = model.device
        self.debug = debug

        if not isinstance(alpha, float):
            alpha = np.asarray(alpha)
        self.alpha = alpha

        self.t = None

    def calibrate(self, cal_dataset):
        cal_dataset = prepare_numpy_dataset(
            self.model, cal_dataset, ['y_prob', 'y_true'], debug=self.debug)
        y_prob = cal_dataset['y_prob']
        y_true = cal_dataset['y_true']

        N, K = cal_dataset['y_prob'].shape
        if isinstance(self.alpha, float):
            t = _query_quantile(y_prob[np.arange(N), y_true], self.alpha)
        else:
            t = [_query_quantile(y_prob[y_true==k,k],self.alpha[k]) for k in range(K)]
        self.t = torch.tensor(t, device=self.device)

    def forward(self, **kwargs) -> Dict[str, torch.Tensor]:
        """Forward propagation (just like the original model).

        Returns:
            A dictionary with all results from the base model, with the following updates:
                y_predset: a bool tensor representing the prediction for each class.
        """
        pred = self.model(**kwargs)
        pred['y_predset'] = pred['y_prob'] > self.t
        return pred
