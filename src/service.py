from typing import List

from bentoml import BentoService, api, artifacts
from bentoml.adapters import JsonInput
from bentoml.types import JsonSerializable
from bentoml.service import BentoServiceArtifact

import pickle
import os
import shutil
import collections
import tempfile
import subprocess
import numpy as np

CHECKPOINTS_BASEDIR = "checkpoints"
FRAMEWORK_BASEDIR = "framework"

def load_model(framework_dir, checkpoints_dir):
    mdl = Model()
    mdl.load(framework_dir, checkpoints_dir)
    return mdl


class Model(object):
    def __init__(self):
        self.DATA_FILE = "data.csv"
        self.FEATURES_FILE = "features.npz"
        self.PRED_FILE = "pred.npz"
        self.RUN_FILE = "run.sh"
        self.LOG_FILE = "run.log"

    def load(self, framework_dir, checkpoints_dir):
        self.framework_dir = framework_dir
        self.checkpoints_dir = checkpoints_dir

    def set_checkpoints_dir(self, dest):
        self.checkpoints_dir = os.path.abspath(dest)

    def set_framework_dir(self, dest):
        self.framework_dir = os.path.abspath(dest)

    def predict(self, smiles_list):
        tmp_folder = tempfile.mkdtemp()
        data_file = os.path.join(tmp_folder, self.DATA_FILE)
        features_file = os.path.join(tmp_folder, self.FEATURES_FILE)
        pred_file = os.path.join(tmp_folder, self.PRED_FILE)
        log_file = os.path.join(tmp_folder, self.LOG_FILE)
        with open(data_file, "w") as f:
            f.write("smiles"+os.linesep)
            for smiles in smiles_list:
                f.write(smiles + os.linesep)
        run_file = os.path.join(tmp_folder, self.RUN_FILE)
        with open(run_file, "w") as f:
            lines = [
                "python {0}/grover/scripts/save_features.py --data_path {1} --save_path {2} --features_generator rdkit_2d_normalized --restart".format(
                    self.framework_dir,
                    data_file,
                    features_file,
                ),
                "python {0}/grover/main.py fingerprint --data_path {1} --features_path {2} --checkpoint_path {3}/grover_large.pt --fingerprint_source both --output {4} --no_cuda".format(
                    self.framework_dir,
                    data_file,
                    features_file,
                    self.checkpoints_dir,
                    pred_file
                )
            ]
            f.write(os.linesep.join(lines))
        cmd = "bash {0}".format(run_file)
        with open(log_file, "w") as fp:
            subprocess.Popen(
                cmd, stdout=fp, stderr=fp, shell=True, env=os.environ
            ).wait()
        V = np.load(pred_file)["fps"]
        R = []
        for i in range(V.shape[0]):
            R += [{"fingerprint": list(V[i,:])}]
        return R


class Artifact(BentoServiceArtifact):
    def __init__(self, name):
        super(Artifact, self).__init__(name)
        self._model = None
        self._extension = ".pkl"

    def _copy_checkpoints(self, base_path):
        src_folder = self._model.checkpoints_dir
        dst_folder = os.path.join(base_path, "checkpoints")
        if os.path.exists(dst_folder):
            os.rmdir(dst_folder)
        shutil.copytree(src_folder, dst_folder)

    def _copy_framework(self, base_path):
        src_folder = self._model.framework_dir
        dst_folder = os.path.join(base_path, "framework")
        if os.path.exists(dst_folder):
            os.rmdir(dst_folder)
        shutil.copytree(src_folder, dst_folder)

    def _model_file_path(self, base_path):
        return os.path.join(base_path, self.name + self._extension)

    def pack(self, model):
        self._model = model
        return self

    def load(self, path):
        model_file_path = self._model_file_path(path)
        model = pickle.load(open(model_file_path, "rb"))
        model.set_checkpoints_dir(
            os.path.join(os.path.dirname(model_file_path), "checkpoints")
        )
        model.set_framework_dir(
            os.path.join(os.path.dirname(model_file_path), "framework")
        )
        return self.pack(model)

    def get(self):
        return self._model

    def save(self, dst):
        self._copy_checkpoints(dst)
        self._copy_framework(dst)
        pickle.dump(self._model, open(self._model_file_path(dst), "wb"))


@artifacts([Artifact("model")])
class Service(BentoService):
    @api(input=JsonInput(), batch=True)
    def predict(self, input: List[JsonSerializable]):
        input = input[0]
        smiles_list = [inp["input"] for inp in input]
        output = self.artifacts.model.predict(smiles_list)
        return [output]
