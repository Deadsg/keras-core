from tensorflow import nest

from keras_core import operations as ops
from keras_core.api_export import keras_core_export
from keras_core.layers.layer import Layer
from keras_core.saving import serialization_lib


@keras_core_export("keras_core.layers.StackedRNNCells")
class StackedRNNCells(Layer):
    """Wrapper allowing a stack of RNN cells to behave as a single cell.

    Used to implement efficient stacked RNNs.

    Args:
      cells: List of RNN cell instances.

    Examples:

    ```python
    batch_size = 3
    sentence_length = 5
    num_features = 2
    new_shape = (batch_size, sentence_length, num_features)
    x = np.reshape(np.arange(30), new_shape)

    rnn_cells = [keras_core.layers.LSTMCell(128) for _ in range(2)]
    stacked_lstm = keras_core.layers.StackedRNNCells(rnn_cells)
    lstm_layer = keras_core.layers.RNN(stacked_lstm)

    result = lstm_layer(x)
    ```
    """

    def __init__(self, cells, **kwargs):
        super().__init__(**kwargs)
        for cell in cells:
            if "call" not in dir(cell):
                raise ValueError(
                    "All cells must have a `call` method. "
                    f"Received cell without a `call` method: {cell}"
                )
            if "state_size" not in dir(cell):
                raise ValueError(
                    "All cells must have a `state_size` attribute. "
                    f"Received cell without a `state_size`: {cell}"
                )
        self.cells = cells

    @property
    def state_size(self):
        return [c.state_size for c in self.cells]

    @property
    def output_size(self):
        if getattr(self.cells[-1], "output_size", None) is not None:
            return self.cells[-1].output_size
        elif isinstance(self.cells[-1].state_size, (list, tuple)):
            return self.cells[-1].state_size[0]
        else:
            return self.cells[-1].state_size

    def get_initial_state(self, batch_size=None):
        initial_states = []
        for cell in self.cells:
            get_initial_state_fn = getattr(cell, "get_initial_state", None)
            if get_initial_state_fn:
                initial_states.append(
                    get_initial_state_fn(batch_size=batch_size)
                )
            else:
                if isinstance(cell.state_size, int):
                    state_size = [cell.state_size]
                else:
                    state_size = cell.state_size
                initial_states.append(
                    [
                        ops.zeros((batch_size, d), dtype=self.compute_dtype)
                        for d in state_size
                    ]
                )
        return initial_states

    def call(self, inputs, states, training=False, **kwargs):
        # Call the cells in order and store the returned states.
        new_states = []
        for cell, states in zip(self.cells, states):
            states = list(states) if nest.is_nested(states) else [states]
            if isinstance(cell, Layer) and cell._call_has_training_arg():
                kwargs["training"] = training
            else:
                kwargs.pop("training", None)
            cell_call_fn = cell.__call__ if callable(cell) else cell.call
            print("call", cell.__class__, "with", states)
            inputs, states = cell_call_fn(inputs, states, **kwargs)
            new_states.append(states)
        return inputs, new_states

    def build(self, input_shape):
        print("build called")
        for cell in self.cells:
            if isinstance(cell, Layer) and not cell.built:
                print("build cell", cell)
                cell.build(input_shape)
                cell.built = True
                print(cell, len(cell.trainable_weights))
            if getattr(cell, "output_size", None) is not None:
                output_dim = cell.output_size
            elif isinstance(cell.state_size, (list, tuple)):
                output_dim = cell.state_size[0]
            else:
                output_dim = cell.state_size
            batch_size = nest.flatten(input_shape)[0]
            input_shape = (batch_size, output_dim)
        self.built = True
        print(self, len(self.trainable_weights))

    def get_config(self):
        cells = []
        for cell in self.cells:
            cells.append(serialization_lib.serialize_keras_object(cell))
        config = {"cells": cells}
        base_config = super().get_config()
        return {**base_config, **config}

    @classmethod
    def from_config(cls, config, custom_objects=None):
        cells = []
        for cell_config in config.pop("cells"):
            cells.append(
                serialization_lib.deserialize_keras_object(
                    cell_config, custom_objects=custom_objects
                )
            )
        return cls(cells, **config)