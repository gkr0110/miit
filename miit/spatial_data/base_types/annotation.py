from collections import OrderedDict
import json
import uuid
from dataclasses import dataclass, field
from os.path import exists, join
from typing import Any, ClassVar, Dict, List, Optional, Tuple, Union


import cv2
import numpy, numpy as np
import SimpleITK as sitk


from miit.registerers.base_registerer import Registerer, RegistrationResult
from miit.spatial_data.base_types.base_imaging import BaseImage
from miit.utils.utils import create_if_not_exists


@dataclass(kw_only=True)
class Annotation(BaseImage):
    """
    Annotations consists of a spatially resolved map of discrete 
    classes. Classes can either be scalar of vector valued. Annotations
    are either single- or multichannel. Singlechannel annotations are
    either of shape W x H x C or W x H where each channel is assumed to be
    binary. Multichannel annotations are of shape W X H where each pixel is an
    integer value presentation either no class (0) or a class (> 0). 

    Image transformations applied to annotations should use a 
    nearest neighbor interpolation to not introduce new classes.
    """

    interpolation_mode: ClassVar[str] = 'NN'
    labels: Optional[Union[List[str], Dict[str, int]]] = None
    is_multichannel: bool = False

    def __post_init__(self) -> None:
        super().__post_init__()
        if self.labels is None:
            if self.is_multichannel:
                labels = {int(x): int(x) for x in np.unique(self.data) if x != 0}
            else:
                if len(self.data.shape) == 2:
                    labels = [1]
                else:
                    labels = list(1, range(self.data.shape[-1] + 1))
            self.labels = labels 

    def crop(self, xmin: int, xmax: int, ymin: int, ymax: int):
        # TODO: Add check for image bounds
        if len(self.data.shape) == 2:
            self.data = self.data[xmin:xmax, ymin:ymax]
        else:
            self.data = self.data[xmin:xmax, ymin:ymax, :]

    def resize(self, width: int, height: int):
        if len(self.data.shape) == 2:
            # TODO: Rewrite that with skimage's resize function
            self.data = cv2.resize(self.data, (height, width), interpolation=cv2.INTER_NEAREST)
        else:
            # Didn't find a better rescale function yet.
            new_image_data = np.zeros((width, height, self.data.shape[2]), dtype=self.data.dtype)
            for i in range(self.data.shape[2]):
                # Use cv as it performs significantly faster on larger images.
                new_image_data[:, :, i] = cv2.resize(self.data[:, :, i], (height, width), interpolation=cv2.INTER_NEAREST)
            self.data = new_image_data

    def rescale(self, scaling_factor: float):
        w, h = self.data.shape[:2]
        w_n, h_n = int(w*scaling_factor), int(h*scaling_factor)
        self.resize(w_n, h_n)            

    def pad(self, padding: Tuple[int, int, int, int], constant_values: int = 0):
        left, right, top, bottom = padding
        if len(self.data.shape) == 2:
            self.data = np.pad(self.data, ((top, bottom), (left, right)), constant_values=constant_values)
        else:
            # Assume 3 dimensions
            self.data = np.pad(self.data, ((top, bottom), (left, right), (0, 0)), constant_values=constant_values)

    def flip(self, axis: int = 0):
        self.data = np.flip(self.data, axis=axis)

    def apply_transform(self, registerer: Registerer, transformation: RegistrationResult, **kwargs: Dict) -> Any:
        transformed_image = self.transform(registerer, transformation, **kwargs)
        return Annotation(data=transformed_image,
                          labels=self.labels,
                          name=self.name)

    def copy(self):
        return Annotation(data=self.data.copy(),
                          labels=self.labels,
                          name=self.name,
                          is_multichannel=self.is_multichannel)

    def store(self, path: str):
        # Use path as a directory here.
        create_if_not_exists(path)
        fname = 'annotations.nii.gz'
        img_path = join(path, fname)
        sitk.WriteImage(sitk.GetImageFromArray(self.data), img_path)
        additional_attributes = {
            'name' : self.name,
            'id': str(self._id)
        }
        with open(join(path, 'additional_attributes.json'), 'w') as f:
            json.dump(additional_attributes, f)
        if self.labels:
            with open(join(path, 'labels.json'), 'w') as f:
                json.dump(self.labels, f)            

    def get_by_label(self, label: str) -> Optional[numpy.ndarray]:
        """Returns a mask for the specified label.

        Args:
            label (str): Label to return.

        Returns:
            Optional[numpy.ndarray]: Either a binary mask or None.
        """
        if not self.labels:
            return None
        if self.is_multichannel:
            idx = self.labels.get(label, None)
            if idx is None:
                return None
            return self.data[self.data == idx]
        else:
            try:
                idx = self.labels.index(label)
                return self.data[:,:,idx]
            except ValueError:
                return None
            
    def convert_to_multichannel(self):
        """Converts an Annotation object to multichannel. 
        
        Note: If a pixel is assigned more than one class in a singlechannel mode,
        converting to multichannel mode will only preserve on class.
        """
        if self.is_multichannel:
            return
        if len(self.data.shape) == 2:
            self.data = np.expand_dims(self.data, -1)
        mc_mat = np.zeros(self.data.shape[:2], dtype=self.data.dtype)
        label_dict = OrderedDict()
        for i in range(self.data.shape[-1]):
            if self.labels:
                label_name = self.labels[i]
            else:
                label_name = i
            mat = self.data[:,:,i]
            label_dict[label_name] = i + 1
            mc_mat[mat == 1] = i + 1
        self.data = mc_mat
        self.labels = label_dict
        self.is_multichannel = True

    def convert_to_singlechannel(self):
        """
        Converts the Annotation object to a multichannel object.
        """
        if not self.is_multichannel:
            return
        h, w = self.data.shape
        c = len(self.labels)
        sc_mat = np.zeros((h, w, c), dtype=self.data.dtype)
        labels = []
        for label_name in self.labels:
            idx = self.labels[label_name]
            sc_mat[:,:,idx-1] = (self.data == idx).astype(self.data.dtype)
            labels.append(label_name)
        self.labels = labels
        self.data = sc_mat
        self.is_multichannel = False              

    def get_resolution(self) -> Optional[float]:
        return self.meta_information.get('resolution', None)

    @staticmethod
    def get_type() -> str:
        return 'annotation'

    @classmethod
    def load(cls, path: str) -> 'Annotation':
        annotation = sitk.GetArrayFromImage(sitk.ReadImage(join(path, 'annotations.nii.gz')))
        labels_path = join(path, 'labels.json')
        if exists(labels_path):
            with open(labels_path) as f:
                labels = json.load(f)
        else:
            labels = None
        with open(join(path, 'additional_attributes.json')) as f:
            additional_attributes = json.load(f)
        name = additional_attributes['name']
        id_ = uuid.UUID(additional_attributes['id'])
        annotation = cls(data=annotation, labels=labels, name=name)
        annotation._id = id_
        return annotation

    @classmethod
    def load_from_path(cls, 
                       path_to_data: str, 
                       path_to_labels: Optional[str] = None,
                       name: str = '',
                       is_multichannel: bool = False,
                       channel_idx: int = -1) -> 'Annotation':
        """Loads an Annotation object.

        Args:
            path_to_data (str): Path to spatial data. 
            path_to_labels (Optional[str], optional): Path to labels file. Labels are a separated by a newline. In None, default labels are derived. Defaults to None.
            name (str, optional): Optional object identifier. Defaults to ''.
            is_multichannel (bool, optional): Indicates whether the image is single- or multichannel. Defaults to False.
            channel_idx (int, optional): Denotes the channel index of the image data. Ignored if annotation has shape W x H. Defaults to -1.

        Returns:
            Annotation: Initialized Annotation object.
        """
        data = sitk.GetArrayFromImage(sitk.ReadImage(path_to_data))
        if path_to_labels is not None:
            with open(path_to_labels) as f:
                labels = [x.strip() for x in f.readlines()]
            if is_multichannel:
                ids = np.unique(data).astype(int)
                ids = sorted([x for x in ids if x != 0])
                labels = {x: y for (x,y) in zip(ids, labels)}
        else:
            labels = None
        if len(data.shape) > 2 and channel_idx != -1:
            data = np.moveaxis(data, channel_idx, -1)
        return cls(data=data, labels=labels, is_multichannel=is_multichannel, name=name)