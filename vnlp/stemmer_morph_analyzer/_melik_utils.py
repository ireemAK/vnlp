import numpy as np
import tensorflow as tf

from ._yildiz_data_utils import sentence_generator

def create_model(num_max_analysis, stem_max_len, char_vocab_size, char_embed_size, stem_num_rnn_units,
                 tag_max_len, tag_vocab_size, tag_embed_size, tag_num_rnn_units,
                 sentence_max_len, surface_token_max_len, embed_join_type = 'add', dropout = 0.2,
                 num_rnn_stacks = 1):
    # Below is a must condition for network to work
    surface_num_rnn_units = stem_num_rnn_units + tag_num_rnn_units

    # character-level embedding layer
    char_embedding = tf.keras.layers.Embedding(char_vocab_size, char_embed_size)
    tag_embedding = tf.keras.layers.Embedding(tag_vocab_size, tag_embed_size)

    # R
    # - Stem Embedding
    stem_input = tf.keras.layers.Input(shape = (num_max_analysis, stem_max_len))
    stem_embedded = char_embedding(stem_input)
    
    stem_rnn = tf.keras.models.Sequential()
    for n in range(num_rnn_stacks - 1):
        stem_rnn.add(tf.keras.layers.Bidirectional(tf.keras.layers.GRU(stem_num_rnn_units, return_sequences = True)))
        stem_rnn.add(tf.keras.layers.Dropout(dropout))
    stem_rnn.add(tf.keras.layers.Bidirectional(tf.keras.layers.GRU(stem_num_rnn_units)))
    stem_rnn.add(tf.keras.layers.Dropout(dropout))
    
    td_stem_rnn = tf.keras.layers.TimeDistributed(stem_rnn, input_shape = (num_max_analysis, stem_max_len, char_embed_size))(stem_embedded)

    # - Tag Embedding
    tag_input = tf.keras.layers.Input(shape = (num_max_analysis, tag_max_len))
    tag_embedded = tag_embedding(tag_input)
    
    tag_rnn = tf.keras.models.Sequential()
    for n in range(num_rnn_stacks - 1):
        tag_rnn.add(tf.keras.layers.Bidirectional(tf.keras.layers.GRU(stem_num_rnn_units, return_sequences = True)))
        tag_rnn.add(tf.keras.layers.Dropout(dropout))
    tag_rnn.add(tf.keras.layers.Bidirectional(tf.keras.layers.GRU(tag_num_rnn_units)))
    tag_rnn.add(tf.keras.layers.Dropout(dropout))
    
    td_tag_rnn = tf.keras.layers.TimeDistributed(tag_rnn, input_shape = (num_max_analysis, tag_max_len, tag_embed_size))(tag_embedded)

    # - Join Stem and Tag Embeddings either Add or Concatenate
    if embed_join_type == 'add':
        joined_stem_tag = tf.keras.layers.Add()([td_stem_rnn, td_tag_rnn])
    elif embed_join_type == 'concat':
        joined_stem_tag = tf.keras.layers.Concatenate()([td_stem_rnn, td_tag_rnn])

    R = tf.keras.layers.Activation(tf.nn.tanh)(joined_stem_tag)

    # =============================================================================

    # h (Sentence surface embedding)
    # - Left to Right Context
    surface_input_left = tf.keras.layers.Input(shape = (sentence_max_len, surface_token_max_len))
    surface_embedded_left = char_embedding(surface_input_left)

    surface_rnn_left = tf.keras.models.Sequential()
    for n in range(num_rnn_stacks - 1):
        surface_rnn_left.add(tf.keras.layers.Bidirectional(tf.keras.layers.GRU(stem_num_rnn_units, return_sequences = True)))
        surface_rnn_left.add(tf.keras.layers.Dropout(dropout))
    surface_rnn_left.add(tf.keras.layers.Bidirectional(tf.keras.layers.GRU(surface_num_rnn_units)))
    surface_rnn_left.add(tf.keras.layers.Dropout(dropout))
    
    td_surface_rnn_left = tf.keras.layers.TimeDistributed(surface_rnn_left, input_shape = (sentence_max_len, surface_token_max_len, char_embed_size))(surface_embedded_left)
    surface_left_context = tf.keras.layers.GRU(surface_num_rnn_units)(td_surface_rnn_left) # This is not bidirectional, but left to right

    # - Right to Left Context
    surface_input_right = tf.keras.layers.Input(shape = (sentence_max_len, surface_token_max_len))
    surface_embedded_right = char_embedding(surface_input_right)

    surface_rnn_right = tf.keras.models.Sequential()
    for n in range(num_rnn_stacks - 1):
        surface_rnn_right.add(tf.keras.layers.Bidirectional(tf.keras.layers.GRU(stem_num_rnn_units, return_sequences = True)))
        surface_rnn_right.add(tf.keras.layers.Dropout(dropout))
    surface_rnn_right.add(tf.keras.layers.Bidirectional(tf.keras.layers.GRU(surface_num_rnn_units)))
    surface_rnn_right.add(tf.keras.layers.Dropout(dropout))
    
    td_surface_rnn_right = tf.keras.layers.TimeDistributed(surface_rnn_right, input_shape = (sentence_max_len, surface_token_max_len, char_embed_size))(surface_embedded_right)
    surface_right_context = tf.keras.layers.GRU(surface_num_rnn_units, go_backwards = True)(td_surface_rnn_right) # This is right to left

    # - Join Right and Left Surface Context either Add or Concatenate
    if embed_join_type == 'add':
        joined_left_right_surface = tf.keras.layers.Add()([surface_left_context, surface_right_context])
    elif embed_join_type == 'concat':
        joined_left_right_surface = tf.keras.layers.Concatenate()([surface_left_context, surface_right_context])

    h = tf.keras.layers.Activation(tf.nn.tanh)(joined_left_right_surface)

    # =============================================================================

    # p
    p = tf.keras.layers.Dot(axes = (2, 1))([R, h])
    p = tf.keras.layers.Dense(num_max_analysis * 2, activation = 'tanh')(p)
    p = tf.keras.layers.Dropout(dropout)(p)
    p = tf.keras.layers.Dense(num_max_analysis, activation = tf.keras.activations.softmax)(p)

    # Model
    model = tf.keras.models.Model(inputs = [stem_input, tag_input, surface_input_left, surface_input_right], outputs = p)

    return model


def convert_data_to_sentence_form(file):
    f = open(file, 'r', encoding = 'utf-8')

    data = []
    sentence = []
    analysis = []
    sentence_flag = False
    for line in f:
        tokens_in_line = line.rstrip().split()
        
        if sentence_flag & (tokens_in_line[0] != "</S>"):
            sentence.append(tokens_in_line[0])
            analysis.append([t.replace('^', '+') for t in tokens_in_line[1:]])
        
        if tokens_in_line[0] == "<S>":
            sentence_flag = True
        elif tokens_in_line[0] == "</S>":
            sentence_flag = False
            
            # I add the if below because there are 7 instances of empty sentence analysis pairs
            # which cause error in data generator
            if (len(sentence) > 0) & (len(analysis)> 0):
                data.append([sentence, analysis])
                sentence = []
                analysis = []

    return data


def fit_tokenizer_char(files, tokenizer_char_oov = '<OOV>', data_processor = 'yildiz'):
    # Fitting char-level tokenizer_char according to surface-form words
    # Surface-form cover the stems as well, so there is no conflict or inconsistency here
    surface_form_tokens = []
    for file in files:
        
        # to use eray yildiz's analyzer to generate senteneces
        if data_processor == 'yildiz':
            data = []
            for s in sentence_generator(file):
                data.append(s)
        # to generate sentences for training without any analyzer
        else:
            data = convert_data_to_sentence_form(file)
            
        for idx in range(len(data)):
            tokens_of_sentence = [token for token in data[idx][0]] #This is not lowered because stem can be proper noun

            surface_form_tokens += tokens_of_sentence

    #This is not lowered because stem can be proper noun with Capital letter
    tokenizer_char = tf.keras.preprocessing.text.Tokenizer(char_level = True, lower = False, filters = None, 
                                                        oov_token = tokenizer_char_oov)
    tokenizer_char.fit_on_texts(surface_form_tokens)

    return tokenizer_char

def fit_tokenizer_tag(files, tokenizer_tag_oov = '<OOV>', data_processor = 'yildiz'):
    # Fitting tags to Tokenizer
    unique_tags = []
    for file in files:

        # to use eray yildiz's analyzer to generate senteneces
        if data_processor == 'yildiz':
            data = []
            for s in sentence_generator(file):
                data.append(s)
        # to generate sentences for training without any analyzer
        else:
            data = convert_data_to_sentence_form(file)
            
        for idx in range(len(data)):
            # 3D
            tags_of_sentence = data[idx][1]

            for tags_of_token in tags_of_sentence:
                # 2D
                for tags_of_single_analysis in tags_of_token:
                    tags = tags_of_single_analysis.split('+')[1:]
                    unique_tags.append(tags)

        tokenizer_tag = tf.keras.preprocessing.text.Tokenizer(lower = False, filters = None, oov_token = tokenizer_tag_oov)
        tokenizer_tag.fit_on_texts(unique_tags)

    return tokenizer_tag

def tokenize_stems_tags(data, tokenizer_char, tokenizer_tag, stem_max_len, tag_max_len, 
                        num_max_analysis, exclude_unambigious, shuffle):
    batch_of_stems = []
    batch_of_tags = []
    batch_of_labels = []
    for idx in range(len(data)):
        num_tokens_in_sentence = len(data[idx][0])
        
        for j in range(num_tokens_in_sentence):
            # If there is no ambiguity
            tag_candidates = [cand.split('+')[1:] for cand in data[idx][1][j]]
            if (len(tag_candidates) == 1) & exclude_unambigious:
                continue
                
            stem_candidates = [cand.split('+')[0] for cand in data[idx][1][j]]
            tokenized_stems = tokenizer_char.texts_to_sequences(stem_candidates)
            tokenized_stems = tf.keras.preprocessing.sequence.pad_sequences(tokenized_stems, 
                                                                            maxlen = stem_max_len, 
                                                                            padding = 'pre')
            tokenized_stems = tokenized_stems[:num_max_analysis] # truncation
            
            tokenized_tags = tokenizer_tag.texts_to_sequences(tag_candidates)
            tokenized_tags = tf.keras.preprocessing.sequence.pad_sequences(tokenized_tags, maxlen = tag_max_len, padding = 'pre')
            tokenized_tags = tokenized_tags[:num_max_analysis] # truncation
            label = np.full(len(tokenized_tags), 0) # create an array of 0s indicating negative class
            label[0] = 1 # positive class is 1
            
            
            # 2D padding with zeros
            # final shape: (num_max_analysis, tag_max_len)
            tokenized_stems = tokenized_stems.tolist()
            tokenized_tags = tokenized_tags.tolist()
            label = label.tolist()
            
            # 2D padding for stem
            for _ in range(max(num_max_analysis - len(tokenized_stems), 0)):
                tokenized_stems.append(np.zeros(stem_max_len))
            
            # 2D padding for tag
            for _ in range(max(num_max_analysis - len(tokenized_tags), 0)):
                tokenized_tags.append(np.zeros(tag_max_len))
                label.append(0) # padding

            tokenized_stems = np.array(tokenized_stems)
            tokenized_tags = np.array(tokenized_tags)
            label = np.array(label)
           
            if shuffle:
                # Shuffling the tags and labels before padding
                def unison_shuffled_copies(a, b, c):
                    assert len(a) == len(b) == len(c)
                    p = np.random.permutation(len(a))
                    return a[p], b[p], c[p]

                tokenized_stems, tokenized_tags, label = unison_shuffled_copies(tokenized_stems, tokenized_tags, label)

            batch_of_stems.append(tokenized_stems)
            batch_of_tags.append(tokenized_tags)
            batch_of_labels.append(label)
            

    batch_of_stems = np.array(batch_of_stems)
    batch_of_tags = np.array(batch_of_tags)
    batch_of_labels = np.array(batch_of_labels)

    return (batch_of_stems, batch_of_tags, batch_of_labels)


def tokenize_surface_form_context(data, tokenizer_char, surface_token_max_len, sentence_max_len, exclude_unambigious = False):
    batch_of_left_context = []
    batch_of_right_context = []
    for idx in range(len(data)):
        raw_tokens_in_sentence = data[idx][0]
        num_tokens_in_sentence = len(raw_tokens_in_sentence)
        
        for j in range(num_tokens_in_sentence):
            # If there is no ambiguity
            tag_candidates = [cand.split('+')[1:] for cand in data[idx][1][j]]
            if (len(tag_candidates) == 1) & exclude_unambigious:
                continue
            
            # LEFT CONTEXT
            # there is no left context for the first token
            if j== 0:
                tokenized_left_context = np.zeros((sentence_max_len, surface_token_max_len))
                
            else:
                tokens_in_left = raw_tokens_in_sentence[:j]
                tokenized_left_context = tokenizer_char.texts_to_sequences(tokens_in_left)
                tokenized_left_context = tf.keras.preprocessing.sequence.pad_sequences(tokenized_left_context, 
                                                                                    maxlen = surface_token_max_len, 
                                                                                    padding = 'pre')
            # 2D padding with zeros
            # final shape: (sentence_max_len, stem_max_len)
            tokenized_left_context = tokenized_left_context.tolist()
            
            # truncating in case number of tokens on left context are larger than max
            if len(tokenized_left_context)> sentence_max_len:
                tokenized_left_context = tokenized_left_context[-sentence_max_len:] # cropping the first part
            
            # 2D padding with zeros
            for _ in range(max(sentence_max_len - len(tokenized_left_context), 0)):
                tokenized_left_context.append(np.zeros(surface_token_max_len))
            tokenized_left_context = np.array(tokenized_left_context)
            
            assert tokenized_left_context.shape == (sentence_max_len, surface_token_max_len)
            
            batch_of_left_context.append(tokenized_left_context)

            # =================================================
            
            # RIGHT CONTEXT
            # there is no right context for the last token
            if j == (num_tokens_in_sentence -1):
                tokenized_right_context = np.zeros((sentence_max_len, surface_token_max_len))
                
            else:
                tokens_in_right = raw_tokens_in_sentence[(j+1):]
                tokenized_right_context = tokenizer_char.texts_to_sequences(tokens_in_right)
                tokenized_right_context = tf.keras.preprocessing.sequence.pad_sequences(tokenized_right_context, 
                                                                                    maxlen = surface_token_max_len, 
                                                                                    padding = 'post')
            # 2D padding with zeros
            # final shape: (sentence_max_len, stem_max_len)
            tokenized_right_context = tokenized_right_context.tolist()
            
            # truncating in case number of tokens on left context are larger than max
            if len(tokenized_right_context)> sentence_max_len:
                tokenized_right_context = tokenized_right_context[:sentence_max_len] # cropping the last part
            
            # 2D padding with zeros
            for _ in range(max(sentence_max_len - len(tokenized_right_context), 0)):
                tokenized_right_context.append(np.zeros(surface_token_max_len))
            tokenized_right_context = np.array(tokenized_right_context)
            
            assert tokenized_right_context.shape == (sentence_max_len, surface_token_max_len)
            
            batch_of_right_context.append(tokenized_right_context)
            
    batch_of_left_context = np.array(batch_of_left_context)
    batch_of_right_context = np.array(batch_of_right_context)

    return (batch_of_left_context, batch_of_right_context)


def process_data(data, tokenizer_char, tokenizer_tag, stem_max_len, tag_max_len, surface_token_max_len, 
                sentence_max_len, num_max_analysis, exclude_unambigious, shuffle):
    stems, tags, labels = tokenize_stems_tags(data, tokenizer_char, tokenizer_tag, 
                                              stem_max_len, tag_max_len, num_max_analysis, exclude_unambigious, shuffle)
    left_context, right_context = tokenize_surface_form_context(data, tokenizer_char, surface_token_max_len,
                                                                sentence_max_len, exclude_unambigious)

    return ((stems, tags, left_context, right_context), labels)

def data_generator(files, batch_size, tokenizer_char, tokenizer_tag, stem_max_len = 10, tag_max_len = 15, surface_token_max_len = 15, 
                sentence_max_len = 40, num_max_analysis = 10, exclude_unambigious = False, shuffle = True, data_processor = 'yildiz'):

    # to use eray yildiz's analyzer to generate senteneces
    if data_processor == 'yildiz':
        data = []
        for file in files:
            for s in sentence_generator(file):
                data.append(s)
    # to generate sentences for training without any analyzer
    else:
        data = []
        for file in files:
            data += convert_data_to_sentence_form(file)

    while True:
        stems = np.array([])
        while stems.shape[0] < batch_size:
            rand_sentence_idx = np.random.randint(0, len(data), 1)[0]
            if stems.shape[0] == 0:
                ((stems, tags, left_context, right_context), labels) = process_data([data[rand_sentence_idx]], tokenizer_char, tokenizer_tag, stem_max_len, tag_max_len, surface_token_max_len, 
                                sentence_max_len, num_max_analysis, exclude_unambigious, shuffle)
            else:
                ((stems_, tags_, left_context_, right_context_), labels_) = process_data([data[rand_sentence_idx]], tokenizer_char, tokenizer_tag, stem_max_len, tag_max_len, surface_token_max_len, 
                        sentence_max_len, num_max_analysis, exclude_unambigious, shuffle)

                stems = np.vstack((stems, stems_))
                tags = np.vstack((tags, tags_))
                left_context = np.vstack((left_context, left_context_))
                right_context = np.vstack((right_context, right_context_))
                labels = np.vstack((labels, labels_))

        yield (stems[:batch_size], tags[:batch_size], left_context[:batch_size],
               right_context[:batch_size]), labels[:batch_size]
