import os
import glob
import dlib
import torch
import torch.nn as nn
from torch.autograd import Variable
from enum import Enum
from skimage import io
import urllib.request

from .models import FAN, ResNetDepth
from .utils import *


class LandmarksType(Enum):
    _2D = 1
    _2halfD = 2
    _3D = 3


class NetworkSize(Enum):
    #TINY = 1
    #SMALL = 2
    #MEDIUM = 3
    LARGE = 4

    def __new__(cls, value):
        member = object.__new__(cls)
        member._value_ = value
        return member

    def __int__(self):
        return self.value


class FaceAlignment:
    """Initialize the face alignment pipeline

    Args:
        landmarks_type (``LandmarksType`` object): an enum defining the type of predicted points.
        network_size (``NetworkSize`` object): an enum defining the size of the network (for the 2D and 2.5D points).
        enable_cuda (bool, optional): If True, all the computations will be done on a CUDA-enabled GPU (recommended).
        enable_cudnn (bool, optional): If True, cudnn library will be used
        flip_input (bool, optional): Increase the network accuracy by doing a second forward passed with the flipped version of the image

    Example:
        >>> FaceAlignment(NetworkSize.2D, flip_input=False)
    """

    def __init__(self, landmarks_type, network_size=NetworkSize.LARGE,
                 enable_cuda=True, enabled_cudnn=True, flip_input=False):
        self.enable_cuda = enable_cuda
        self.flip_input = flip_input
        self.landmarks_type = landmarks_type
        base_path = os.path.join(appdata_dir('face_alignment'), "data")
        # Initialise the face detector
        if enable_cuda:
            path_to_detector = os.path.join(
                base_path, "mmod_human_face_detector.dat")
            if not os.path.isfile(path_to_detector):
                if not os.path.exists(base_path):
                    os.makedirs(base_path)
                print("Downloading the face detection CNN. Please wait...")

                urllib.request.urlretrieve(
                    "https://www.adrianbulat.com/downloads/dlib/mmod_human_face_detector.dat",
                    os.path.join(path_to_detector),
                    reporthook)

            self.face_detector = dlib.cnn_face_detection_model_v1(
                path_to_detector)

        else:
            self.face_detector = dlib.get_frontal_face_detector()

        # Initialise the face alignemnt networks
        self.face_alignemnt_net = nn.DataParallel(FAN(int(network_size)))
        if landmarks_type == LandmarksType._2D:
            network_name = '2DFAN-' + str(int(network_size)) + '.pth.tar'
        else:
            network_name = '2DFAN-' + str(int(network_size)) + '.pth.tar'
        fan_path = os.path.join(base_path, network_name)

        if not os.path.isfile(fan_path):
            print("Downloading the Face Alignment Network(FAN). Please wait...")

            urllib.request.urlretrieve(
                "https://www.adrianbulat.com/downloads/python-fan/" +
                network_name, os.path.join(fan_path),
                reporthook)

        fan_weights = torch.load(fan_path)
        self.face_alignemnt_net.load_state_dict(fan_weights['state_dict'])

        if self.enable_cuda:
            self.face_alignemnt_net.cuda()
        self.face_alignemnt_net.train()

        # Initialiase the depth prediciton network
        if landmarks_type == LandmarksType._3D:
            self.depth_prediciton_net = nn.DataParallel(ResNetDepth())
            depth_model_path = os.path.join(base_path, 'depth.pth.tar')
            if not os.path.isfile(depth_model_path):
                print(
                    "Downloading the Face Alignment depth Network (FAN-D). Please wait...")

                urllib.request.urlretrieve(
                    "https://www.adrianbulat.com/downloads/python-fan/depth.pth.tar",
                    os.path.join(depth_model_path),
                    reporthook)

            depth_weights = torch.load(depth_model_path)
            self.depth_prediciton_net.load_state_dict(
                depth_weights['state_dict'])

            if enable_cuda:
                self.depth_prediciton_net.cuda()
            self.depth_prediciton_net.eval()

    def detect_faces(self, image):
        """Run the dlib face detector over an image

        Args:
            image (``ndarray`` object or string): either the path to the image or an image previosly opened on which face detection will be performed.

        Returns:
            Returns a list of detected faces
        """
        return self.face_detector(image, 1)

    def get_landmarks(self, input_image, all_faces=False):
        if isinstance(input_image, str):
            try:
                image = io.imread(input_image)
            except IOError:
                print("error opening file :: ", input_image)
                return None
        else:
            image = input_image

        detected_faces = self.detect_faces(image)
        if len(detected_faces) > 0:
            landmarks = []
            for i, d in enumerate(detected_faces):
                if i > 1 and not all_faces:
                    break
                if self.enable_cuda:
                    d = d.rect

                center = torch.FloatTensor(
                    [d.right() - (d.right() - d.left()) / 2, d.bottom() -
                     (d.bottom() - d.top()) / 2])
                center[1] = center[1] - (d.bottom() - d.top()) * 0.1
                scale = (d.right() - d.left() + d.bottom() - d.top()) / 200

                inp = crop(image, center, scale)
                inp = torch.from_numpy(inp.transpose(
                    (2, 0, 1))).float().div(255.0).unsqueeze_(0)

                if self.enable_cuda:
                    inp.cuda()

                out = self.face_alignemnt_net(
                    Variable(inp, volatile=True))[-1].data.cpu()
                if self.flip_input:
                    out += flip(self.face_alignemnt_net(Variable(flip(inp),
                                                                 volatile=True))[-1].data.cpu(), is_label=True)

                pts, pts_img = get_preds_fromhm(out, center, scale)
                pts, pts_img = pts.view(68, 2) * 4, pts_img.view(68, 2)

                if self.landmarks_type == LandmarksType._3D:
                    heatmaps = np.zeros((68, 256, 256))
                    for i in range(68):
                        if pts[i, 0] > 0:
                            heatmaps[i] = draw_gaussian(heatmaps[i], pts[i], 2)
                    heatmaps = torch.from_numpy(
                        heatmaps).view(1, 68, 256, 256).float()
                    if self.enable_cuda:
                        heatmaps.cuda()
                    depth_pred = self.depth_prediciton_net(
                        Variable(
                            torch.cat(
                                (inp, heatmaps), 1), volatile=True)).data.cpu().view(
                        68, 1)
                    pts_img = torch.cat(
                        (pts_img, depth_pred * (1 / (256 / (200 * scale)))), 1)

                landmarks.append(pts_img.numpy())
                # TODO Remove plot
                import matplotlib.pyplot as plt
                plt.imshow(inp.view(3, 256, 256).float(
                ).numpy().swapaxes(0, 1).swapaxes(1, 2))
                pts = pts.view(68, 2).numpy()
                plt.plot(pts[:, 0], pts[:, 1], 'ro')
                plt.show()
        else:
            print("Warning: No faces were detected.")
            return None

        return landmarks

    def process_folder(self, path, all_faces=False):
        types = ('*.jpg', '.png')
        images_list = []
        for files in types:
            images_list.extend(glob.glob(files))

        predictions = []
        for image_name in images_list:
            predictions.append(
                image_name, self.get_landmarks(image_name, all_faces))

        return predictions