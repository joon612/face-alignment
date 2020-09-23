import face_alignment
from skimage import io
from mpl_toolkits.mplot3d import axes3d
import matplotlib.pyplot as plt
from mpldatacursor import datacursor

fa = face_alignment.FaceAlignment(face_alignment.LandmarksType._3D, device='cpu', flip_input=False)

input = io.imread('test/assets/aflw-test.jpg')
preds = fa.get_landmarks(input)


fig = plt.figure()
ax = fig.add_subplot(111, projection='3d')

def func():
    for i,spot in enumerate(preds[0]):
        print(spot)
        spotX=spot[0]
        spotY=spot[1]
        spotZ=spot[2]
        ax.scatter(spotX,spotY,spotZ,marker='x')
        ax.text(spotX,spotY,spotZ,i)

func()
ax.set_xlabel('X') 
ax.set_ylabel('Y') 
ax.set_zlabel('Z') 
plt.show()