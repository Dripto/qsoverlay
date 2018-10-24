"""
circuit_builder: an overlay for quantumsim to build circuits slightly easier.
Assumes a gate set for a system, and inserts new gates end-on, keeping track
of at what time the next gate can be executed.

Does not do any compilation; this should possibly be inserted later.

TODO: fix up return_flag
"""

import numpy as np
import quantumsim.circuit
import quantumsim.ptm
from .update_functions import update_function_dic


class Builder:

    def __init__(self, setup, **kwargs):
        '''
        Args:
        -------
        setup: an experiment_setup.Setup containing details of
            the experiment.

        kwargs: Can add t1 and t2 via the kwargs instead of
            passing them with the qubit_dic.
        '''
        self.setup = setup
        self.new_circuit(**kwargs)

    def new_circuit(self, circuit_title='New Circuit', **kwargs):

        '''
        Make a new circuit within the builder.
        '''

        self.circuit = quantumsim.circuit.Circuit(circuit_title)

        # Update the circuit list
        self.circuit_list = []

        # Times stores the current time of every qubit (beginning at 0)
        self.times = {}
        self.tmins = {}

        # save_flag is used to keep track of which gates have been
        # saved during a circuit, and needs to be reset here.
        self.save_flag = True

        # Make qubits
        for qubit, qubit_args in sorted(self.setup.qubit_dic.items()):

            if 'classical' in qubit_args.keys() and\
                    qubit_args['classical'] is True:
                self.circuit.add_qubit(quantumsim.circuit.ClassicalBit(qubit))
                continue

            # Get t1 values if we can, otherwise assume infinite.
            if 't1' not in qubit_args.keys():
                if 't1' in kwargs.keys():
                    qubit_args['t1'] = kwargs['t1']
                else:
                    qubit_args['t1'] = np.inf
            if 't2' not in qubit_args.keys():
                if 't2' in kwargs.keys():
                    qubit_args['t2'] = kwargs['t2']
                else:
                    qubit_args['t2'] = np.inf

            self.circuit.add_qubit(qubit, qubit_args['t1'], qubit_args['t2'])

            # Initialise the time of the latest gate on each qubit to 0
            self.times[qubit] = 0
            self.tmins[qubit] = None

    def make_reverse_circuit(self, title='reversed',
                             finalize=True):

        '''
        Generates a new builder with all gates put in the opposite
        order and reversed. (assumes every gate without an angle
        is self-inverse, which is true for CPhase, CNOT, Hadamard
        gates but not for ISwap gates - this is a bug that needs
        to be fixed.)
        '''

        reversed_circuit_list = list(reversed(self.circuit_list))
        for n, gate_desc in enumerate(reversed_circuit_list):
            gate_name = gate_desc[0]

            num_qubits = self.setup.gate_dic[gate_name]['num_qubits']
            user_kws = self.setup.gate_dic[gate_name]['user_kws']

            if 'angle' in user_kws:
                gate_desc = list(gate_desc)
                angle_index = user_kws.index('angle')
                gate_desc[num_qubits + 1 + angle_index] *= -1
                reversed_circuit_list[n] = tuple(gate_desc)

        reversed_circuit_builder = Builder(setup=self.setup)
        reversed_circuit_builder.add_circuit_list(reversed_circuit_list)
        if finalize:
            reversed_circuit_builder.finalize()

        return reversed_circuit_builder

    def add_qasm(self, qasm_generator, qubits_first=True, **params):
        '''
        Converts a qasm file into a circuit.
        qasm_generator should yield lines of qasm when called.

        I assume that qasm lines take the form:
        GATE [arg0, arg1, ..] qubit0 [qubit1, ..]
        Importantly, currently only allowing for a single space
        in between words.
        '''
        returned_gate_list = []
        for line in qasm_generator:

            # Copy kwargs to prevent overwriting
            kwargs = {**params}

            # Get positions of spaces in line
            spaces = [i for i, x in enumerate(line) if x == ',' or x == ' ']
            spaces.append(len(line))

            # Get the gate name
            gate_name = line[:spaces[0]]

            num_qubits = self.setup.gate_dic[gate_name]['num_qubits']
            user_kws = self.setup.gate_dic[gate_name]['user_kws']

            if gate_name == 'measure':
                # line looks like 'measure q -> c;'
                qubit_list = [line[spaces[0]+1:spaces[1]]]
                output_bit = [line[spaces[2]+1:spaces[3]]]
                self.add_gate('Measure', qubit_list,
                              output_bit=output_bit)
                continue

            if qubits_first:
                # Create qubit list
                qubit_list = [line[spaces[j]+1:
                              spaces[j+1]]
                              for j in range(num_qubits)]

                # Add arguments from qasm to kwargs
                for n, kw in enumerate(user_kws):
                    try:
                        kwargs[kw] = float(line[spaces[n+num_qubits]+1:
                                                spaces[n + num_qubits+1]])
                    except:
                        kwargs[kw] = line[spaces[n+num_qubits]+1:
                                          spaces[n+num_qubits+1]]

            else:
                # Add arguments from qasm to kwargs
                for n, kw in enumerate(user_kws):
                    try:
                        kwargs[kw] = float(line[spaces[n]+1:spaces[n+1]])
                    except Exception:
                        kwargs[kw] = line[spaces[n]+1:spaces[n+1]]

                # Create qubit list
                qubit_list = [line[spaces[len(user_kws)+j]+1:
                              spaces[len(user_kws)+j+1]]
                              for j in range(num_qubits)]

            try:
                returned_gate = self.add_gate(gate_name, qubit_list, **kwargs)
                if returned_gate is not None:
                    returned_gate_list.append(returned_gate)
            except Exception as inst:
                print()
                print('Adding gate failed!')
                try:
                    print(kwargs['angle'])
                except:
                    pass
                print(line, gate_name, qubit_list, kwargs)
                raise inst

        return returned_gate_list

    def add_circuit_list(self, circuit_list):

        '''
        Adds a circuit in the list format stored by qsoverlay
        to the builder.
        '''
        adjustable_gates = []
        for gate_desc in circuit_list:
            temp_ag = self < gate_desc
            if temp_ag:
                adjustable_gates.append(temp_ag)
        return adjustable_gates

    def __lt__(self, gate_desc):
        gate_name = gate_desc[0]

        num_qubits = self.setup.gate_dic[gate_name]['num_qubits']
        user_kws = self.setup.gate_dic[gate_name]['user_kws']

        if len(gate_desc) == len(user_kws) + num_qubits + 2:
            return_flag = gate_desc[-1]
        else:
            assert len(gate_desc) == len(user_kws) + num_qubits + 1
            return_flag = False

        qubit_list = gate_desc[1:num_qubits + 1]

        kwargs = {kw: arg for kw, arg in
                  zip(user_kws, gate_desc[num_qubits+1:])}

        return self.add_gate(gate_name, qubit_list,
                             return_flag=return_flag, **kwargs)

    def add_gate(self, gate_name,
                 qubit_list, return_flag=False,
                 **kwargs):
        """
        Adds a gate at the appropriate time to our system.
        The gate is always added in the middle of the time period
        in which it occurs.

        @ gate_name: name of the gate in the gate_set dictionary
        @ qubit_list: list of qubits that the gate acts on (in
            whatever order is appropriate)
        @ kwargs: whatever is additionally necessary for the gate.
            e.g. classical bit output names for a measurement,
                angles for a rotation gate.
            Note: times, or error parameters that can be obtained
                from a qubit will be ignored.
        """

        # The gate tuple is a unique identifier for the gate, allowing
        # for asymmetry (as opposed to the name of the gate, which is
        # the same for every qubit/pair of qubits).
        gate_tuple = (gate_name, *qubit_list)

        circuit_args, builder_args = self.setup.gate_set[gate_tuple]

        # kwargs is the list of arguments that gets passed to the gate
        # itself. We initiate with the set of additional arguments passed
        # by the user and the arguments from the gate dic intended for
        # quantumsim.
        kwargs = {**circuit_args, **kwargs}

        # Find the length of the gate
        gate_time = builder_args['gate_time']

        # Calculate when to apply the gate
        time = max(self.times[qubit] for qubit in qubit_list)
        try:
            kwargs['time'] = time + builder_args['exec_time']

        except:
            # If we have no exec time, assume the gate occurs in the
            # middle of the time window allocated.
            kwargs['time'] = time + gate_time/2

        # Add qubits to the kwargs as appropriate.
        # Note that we do *not* add classical bits here.
        if len(qubit_list) == 1:
            kwargs['bit'] = qubit_list[0]
        else:
            for j, qubit in enumerate(qubit_list):
                kwargs['bit'+str(j)] = qubit

        # Store a representation of the circuit for ease of access.
        # Note that this representation does not account for any
        # standard parameters (i.e. those changed in the gate_set)
        # that are changed by the user.

        # This also ensures that the user has entered all necessary
        # data.
        if self.save_flag:
            user_data = [kwargs[kw]
                         for kw in self.setup.gate_dic[gate_name]['user_kws']]
            if return_flag is not False:
                self.circuit_list.append((gate_name, *qubit_list,
                                          *user_data, return_flag))
            else:
                self.circuit_list.append((gate_name, *qubit_list,
                                          *user_data))

        # Get the gate to add to quantumsim.
        gate = self.setup.gate_dic[gate_name]['function']

        # The save flag prevents saving multiple gate
        # definitions when using recursive gates (i.e.
        # gates that are decomposed and fed back to
        # the builder). We turn it off, and turn it on
        # after the execution of this gate if it was
        # previously on. As this could cause issues
        # when errors occur inserting the gate, we make
        # sure to turn it back afterwards regardless
        # of success.
        prev_flag = self.save_flag
        self.save_flag = False
        try:
            if isinstance(gate, str):
                self.circuit.add_gate(gate, **kwargs)

            elif isinstance(gate, type) and\
                    issubclass(gate, quantumsim.circuit.Gate):
                self.circuit.add_gate(gate(**kwargs))

            else:
                gate(builder=self, **kwargs)

            self.save_flag = prev_flag
        except:
            self.save_flag = prev_flag
            raise

        # Update time on qubits after gate is created
        for qubit in qubit_list:
            self.times[qubit] = max(self.times[qubit], time + gate_time)

            # If this qubit has not been used before, store the start
            # of this gate as the first time it is activated.
            if self.tmins[qubit] is None:
                self.tmins[qubit] = time

        # My current best idea for adjustable gates - return the
        # gate that could be adjusted to the user.
        if return_flag is not False:
            return self.circuit.gates[-int(return_flag)]

    def update(self, **kwargs):
        for rule in self.update_rules:
            update_function_dic[rule](self, **kwargs)

    def finalize(self, topo_order=False, dtmax=0, dtmin=0, shrink=False):
        """
        Script to run to finalize gates. Currently adds waiting gates
        as required and sorts gates.

        Args:
        --------
        topo_order : bool
            whether to toposort gates or simply order them by time.
        dtmax : float or dict of floats
            time to pad qubits by (i.e. dead time after the gates 
            in the circuit are executed). If float, applies same
            padding to all qubits.
        dtmin : float or dict of floats
            time to pad qubits by on the left (i.e. dead time before
            any gates are executed). If float, applies same padding
            to all qubits.
        shrink : bool
            whether to shrink resting gates around qubits. When
        """

        if self.setup.system_params['uses_waiting_gates'] is True:
            self.add_waiting_gates(
                dtmin=dtmin, dtmax=dtmax, shrink=shrink)

        if topo_order is True:
            self.circuit.order()
        else:
            self.circuit.gates = sorted(self.circuit.gates,
                                        key=lambda x: x.time)

    def add_waiting_gates(self, dtmin=0, dtmax=0, shrink=False):
        """
        Function to add waiting gates to system

        Args:
        --------
        dtmax : float or dict of floats
            time to pad qubits by (i.e. dead time after the gates 
            in the circuit are executed). If float, applies same
            padding to all qubits.
        dtmin : float or dict of floats
            time to pad qubits by on the left (i.e. dead time before
            any gates are executed). If float, applies same padding
            to all qubits.
        shrink : bool
            whether to shrink resting gates around qubits. When
        """
        if shrink:
            tmin = self.tmins
            tmax = self.times
        else:
            circuit_time = max(self.times.values())
            tmax = {key: circuit_time for key in self.times.keys()}
            tmin = {key: 0 for key in self.times.keys()}

        if type(dtmax) == dict:
            for key,val in dtmax.items():
                tmax[key] += val
        else:
            for key in tmax.keys():
                tmax[key] += dtmax

        if type(dtmin) == dict:
            for key,val in dtmin.items():
                tmin[key] -= val
        else:
            for key in tmin.keys():
                tmin[key] -= dtmin

        # args = list(self.qubit_dic.values())[0]

        # if 'photons' in args.keys() and args['photons'] is True:
        #     quantumsim.photons.add_waiting_gates_photons(
        #         self.circuit,
        #         tmin=0, tmax=circuit_time,
        #         alpha0=args['alpha0'], kappa=args['kappa'],
        #         chi=args['chi'])
        # else:

        self.circuit.add_waiting_gates(tmin=tmin, tmax=tmax)
