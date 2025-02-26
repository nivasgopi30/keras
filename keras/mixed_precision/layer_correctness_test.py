# Copyright 2019 The TensorFlow Authors. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
# ==============================================================================
"""Tests various Layer subclasses have correct outputs with mixed precision."""

import tensorflow.compat.v2 as tf

from absl.testing import parameterized
import numpy as np
from keras import keras_parameterized
from keras import layers
from keras import models
from keras.layers import advanced_activations
from keras.layers import convolutional
from keras.layers import convolutional_recurrent
from keras.layers import core
from keras.layers import dense_attention
from keras.layers import embeddings
from keras.layers import local
from keras.layers import merge
from keras.layers import noise
from keras.layers import pooling
from keras.layers import recurrent
from keras.layers import recurrent_v2
from keras.layers import reshaping
from keras.layers import wrappers
from keras.layers.normalization import batch_normalization
from keras.layers.normalization import layer_normalization
from keras.layers.preprocessing import image_preprocessing
from keras.layers.preprocessing import normalization
from keras.mixed_precision import policy


def create_mirrored_strategy():
  # The test creates two virtual CPUs, and we use both of them to test with
  # multiple devices.
  return tf.distribute.MirroredStrategy(['cpu:0', 'cpu:1'])


def _create_normalization_layer_with_adapt():
  layer = normalization.Normalization()
  layer.adapt(np.random.normal(size=(10, 4)))
  return layer


def _create_normalization_layer_without_adapt():
  return normalization.Normalization(
      mean=np.random.normal(size=(4,)),
      variance=np.random.uniform(0.5, 2., size=(4,))
  )


class LayerCorrectnessTest(keras_parameterized.TestCase):

  def setUp(self):
    super(LayerCorrectnessTest, self).setUp()
    # Set two virtual CPUs to test MirroredStrategy with multiple devices
    cpus = tf.config.list_physical_devices('CPU')
    tf.config.set_logical_device_configuration(cpus[0], [
        tf.config.LogicalDeviceConfiguration(),
        tf.config.LogicalDeviceConfiguration(),
    ])

  def _create_model_from_layer(self, layer, input_shapes):
    inputs = [layers.Input(batch_input_shape=s) for s in input_shapes]
    if len(inputs) == 1:
      inputs = inputs[0]
    y = layer(inputs)
    model = models.Model(inputs, y)
    model.compile('sgd', 'mse')
    return model

  @parameterized.named_parameters(
      ('LeakyReLU', advanced_activations.LeakyReLU, (2, 2)),
      ('PReLU', advanced_activations.PReLU, (2, 2)),
      ('ELU', advanced_activations.ELU, (2, 2)),
      ('ThresholdedReLU', advanced_activations.ThresholdedReLU, (2, 2)),
      ('Softmax', advanced_activations.Softmax, (2, 2)),
      ('ReLU', advanced_activations.ReLU, (2, 2)),
      ('Conv1D', lambda: convolutional.Conv1D(2, 2), (2, 2, 1)),
      ('Conv2D', lambda: convolutional.Conv2D(2, 2), (2, 2, 2, 1)),
      ('Conv3D', lambda: convolutional.Conv3D(2, 2), (2, 2, 2, 2, 1)),
      ('Conv2DTranspose', lambda: convolutional.Conv2DTranspose(2, 2),
       (2, 2, 2, 2)),
      ('SeparableConv2D', lambda: convolutional.SeparableConv2D(2, 2),
       (2, 2, 2, 1)),
      ('DepthwiseConv2D', lambda: convolutional.DepthwiseConv2D(2, 2),
       (2, 2, 2, 1)),
      ('UpSampling2D', reshaping.UpSampling2D, (2, 2, 2, 1)),
      ('ZeroPadding2D', reshaping.ZeroPadding2D, (2, 2, 2, 1)),
      ('Cropping2D', reshaping.Cropping2D, (2, 3, 3, 1)),
      ('ConvLSTM2D',
       lambda: convolutional_recurrent.ConvLSTM2D(4, kernel_size=(2, 2)),
       (4, 4, 4, 4, 4)),
      ('Dense', lambda: core.Dense(2), (2, 2)),
      ('Dropout', lambda: core.Dropout(0.5), (2, 2)),
      ('SpatialDropout2D', lambda: core.SpatialDropout2D(0.5), (2, 2, 2, 2)),
      ('Activation', lambda: core.Activation('sigmoid'), (2, 2)),
      ('Reshape', lambda: reshaping.Reshape((1, 4, 1)), (2, 2, 2)),
      ('Permute', lambda: reshaping.Permute((2, 1)), (2, 2, 2)),
      ('Attention', dense_attention.Attention, [(2, 2, 3), (2, 3, 3),
                                                (2, 3, 3)]),
      ('AdditiveAttention', dense_attention.AdditiveAttention, [(2, 2, 3),
                                                                (2, 3, 3),
                                                                (2, 3, 3)]),
      ('Embedding', lambda: embeddings.Embedding(4, 4),
       (2, 4), 2e-3, 2e-3, np.random.randint(4, size=(2, 4))),
      ('LocallyConnected1D', lambda: local.LocallyConnected1D(2, 2), (2, 2, 1)),
      ('LocallyConnected2D', lambda: local.LocallyConnected2D(2, 2),
       (2, 2, 2, 1)),
      ('Add', merge.Add, [(2, 2), (2, 2)]),
      ('Subtract', merge.Subtract, [(2, 2), (2, 2)]),
      ('Multiply', merge.Multiply, [(2, 2), (2, 2)]),
      ('Average', merge.Average, [(2, 2), (2, 2)]),
      ('Maximum', merge.Maximum, [(2, 2), (2, 2)]),
      ('Minimum', merge.Minimum, [(2, 2), (2, 2)]),
      ('Concatenate', merge.Concatenate, [(2, 2), (2, 2)]),
      ('Dot', lambda: merge.Dot(1), [(2, 2), (2, 2)]),
      ('GaussianNoise', lambda: noise.GaussianNoise(0.5), (2, 2)),
      ('GaussianDropout', lambda: noise.GaussianDropout(0.5), (2, 2)),
      ('AlphaDropout', lambda: noise.AlphaDropout(0.5), (2, 2)),
      ('BatchNormalization', batch_normalization.BatchNormalization,
       (2, 2), 1e-2, 1e-2),
      ('LayerNormalization', layer_normalization.LayerNormalization, (2, 2)),
      ('LayerNormalizationUnfused',
       lambda: layer_normalization.LayerNormalization(axis=1), (2, 2, 2)),
      ('MaxPooling2D', pooling.MaxPooling2D, (2, 2, 2, 1)),
      ('AveragePooling2D', pooling.AveragePooling2D, (2, 2, 2, 1)),
      ('GlobalMaxPooling2D', pooling.GlobalMaxPooling2D, (2, 2, 2, 1)),
      ('GlobalAveragePooling2D', pooling.GlobalAveragePooling2D, (2, 2, 2, 1)),
      ('SimpleRNN', lambda: recurrent.SimpleRNN(units=4),
       (4, 4, 4), 1e-2, 1e-2),
      ('SimpleRNN_stateful',
       lambda: recurrent.SimpleRNN(units=4, stateful=True),
       (4, 4, 4), 1e-2, 1e-2),
      ('GRU', lambda: recurrent.GRU(units=4), (4, 4, 4)),
      ('LSTM', lambda: recurrent.LSTM(units=4), (4, 4, 4)),
      ('GRUV2', lambda: recurrent_v2.GRU(units=4), (4, 4, 4)),
      ('GRUV2_stateful', lambda: recurrent_v2.GRU(units=4, stateful=True),
       (4, 4, 4)),
      ('LSTMV2', lambda: recurrent_v2.LSTM(units=4), (4, 4, 4)),
      ('LSTMV2_stateful', lambda: recurrent_v2.LSTM(units=4, stateful=True),
       (4, 4, 4)),
      ('TimeDistributed', lambda: wrappers.TimeDistributed(core.Dense(2)),
       (2, 2, 2)),
      ('Bidirectional',
       lambda: wrappers.Bidirectional(recurrent.SimpleRNN(units=4)), (2, 2, 2)),
      ('AttentionLayerCausal', lambda: dense_attention.Attention(causal=True), [
          (2, 2, 3), (2, 3, 3), (2, 3, 3)
      ]),
      ('AdditiveAttentionLayerCausal',
       lambda: dense_attention.AdditiveAttention(causal=True), [(2, 3, 4),
                                                                (2, 3, 4),
                                                                (2, 3, 4)]),
      ('NormalizationAdapt', _create_normalization_layer_with_adapt, (4, 4)),
      ('NormalizationNoAdapt', _create_normalization_layer_without_adapt,
       (4, 4)),
      ('Resizing', lambda: image_preprocessing.Resizing(3, 3), (2, 5, 5, 1)),
      ('Rescaling', lambda: image_preprocessing.Rescaling(2., 1.), (6, 6)),
      ('CenterCrop', lambda: image_preprocessing.CenterCrop(3, 3),
       (2, 5, 5, 1))
  )
  def test_layer(self, f32_layer_fn, input_shape, rtol=2e-3, atol=2e-3,
                 input_data=None):
    """Tests a layer by comparing the float32 and mixed precision weights.

    A float32 layer, a mixed precision layer, and a distributed mixed precision
    layer are run. The three layers are identical other than their dtypes and
    distribution strategies. The outputs after predict() and weights after fit()
    are asserted to be close.

    Args:
      f32_layer_fn: A function returning a float32 layer. The other two layers
        will automatically be created from this
      input_shape: The shape of the input to the layer, including the batch
        dimension. Or a list of shapes if the layer takes multiple inputs.
      rtol: The relative tolerance to be asserted.
      atol: The absolute tolerance to be asserted.
      input_data: A Numpy array with the data of the input. If None, input data
        will be randomly generated
    """

    if f32_layer_fn == reshaping.ZeroPadding2D and tf.test.is_built_with_rocm():
      return
    if isinstance(input_shape[0], int):
      input_shapes = [input_shape]
    else:
      input_shapes = input_shape
    strategy = create_mirrored_strategy()
    f32_layer = f32_layer_fn()

    # Create the layers
    assert f32_layer.dtype == f32_layer._compute_dtype == 'float32'
    config = f32_layer.get_config()
    config['dtype'] = policy.Policy('mixed_float16')
    mp_layer = f32_layer.__class__.from_config(config)
    distributed_mp_layer = f32_layer.__class__.from_config(config)

    # Compute per_replica_input_shapes for the distributed model
    global_batch_size = input_shapes[0][0]
    assert global_batch_size % strategy.num_replicas_in_sync == 0, (
        'The number of replicas, %d, does not divide the global batch size of '
        '%d' % (strategy.num_replicas_in_sync, global_batch_size))
    per_replica_batch_size = (
        global_batch_size // strategy.num_replicas_in_sync)
    per_replica_input_shapes = [(per_replica_batch_size,) + s[1:]
                                for s in input_shapes]

    # Create the models
    f32_model = self._create_model_from_layer(f32_layer, input_shapes)
    mp_model = self._create_model_from_layer(mp_layer, input_shapes)
    with strategy.scope():
      distributed_mp_model = self._create_model_from_layer(
          distributed_mp_layer, per_replica_input_shapes)

    # Set all model weights to the same values
    f32_weights = f32_model.get_weights()
    mp_model.set_weights(f32_weights)
    distributed_mp_model.set_weights(f32_weights)

    # Generate input data
    if input_data is None:
      # Cast inputs to float16 to avoid measuring error from having f16 layers
      # cast to float16.
      input_data = [np.random.normal(size=s).astype('float16')
                    for s in input_shapes]
      if len(input_data) == 1:
        input_data = input_data[0]

    # Assert all models have close outputs.
    f32_output = f32_model.predict(input_data)
    mp_output = mp_model.predict(input_data)
    self.assertAllClose(
        mp_output, f32_output, rtol=rtol, atol=atol)
    self.assertAllClose(
        distributed_mp_model.predict(input_data), f32_output, rtol=rtol,
        atol=atol)

    # Run fit() on models
    output = np.random.normal(size=f32_model.outputs[0].shape).astype('float16')
    for model in f32_model, mp_model, distributed_mp_model:
      model.fit(input_data, output, batch_size=global_batch_size)

    # Assert all models have close weights
    f32_weights = f32_model.get_weights()
    self.assertAllClose(
        mp_model.get_weights(), f32_weights, rtol=rtol, atol=atol)
    self.assertAllClose(
        distributed_mp_model.get_weights(), f32_weights, rtol=rtol, atol=atol)


if __name__ == '__main__':
  tf.compat.v1.enable_v2_behavior()
  tf.test.main()
