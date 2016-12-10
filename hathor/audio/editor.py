import csv

import numpy as np
import matplotlib.pyplot as plt
from moviepy.editor import AudioFileClip, concatenate_audioclips

def generate_audio_volume_array(audio_input):
    '''
    Generate a list of volumes for an audio input
    audio_input     :   Either a AudioFileClip instance, or the name of a file
    '''
    if not isinstance(audio_input, AudioFileClip):
        audio_input = AudioFileClip(audio_input)
    cut = lambda i: audio_input.subclip(i, i+1).to_soundarray(fps=44100)
    volume = lambda array: np.sqrt(((1.0*array)**2).mean())
    volumes = [volume(cut(i)) for i in range(0, int(audio_input.duration-1))]
    return volumes

def _fix_index_overlap(indexes):
    # go back through episodes and make sure there isnt any overlap
    # .. like ( 2, 7 ), (6, 9)
    if len(indexes) == 0:
        return []

    correct_indexes = []
    start_index = indexes[0][0]
    end_index = indexes[0][1]
    count = 1
    while count < len(indexes):
        start = indexes[count][0]
        end = indexes[count][1]
        if end_index < start:
            correct_indexes.append((start_index, end_index))
            start_index = start
        end_index = end
        count += 1
    correct_indexes.append((start_index, end_index))
    return correct_indexes

def guess_commercial_intervals(volume_list):
    total_seconds = len(volume_list)
    volume_average = sum(volume_list) * 1.0 / total_seconds
    commercial_threshold = volume_average * 1.35
    combo_minimum = 12
    # go through the volume list in intervals of 4
    # .. if average of that interval goes over commercial threshold
    # .. save the starting point of the interval as the start index, add a point to the
    # .. "combo" counter, and then check the nex 4 second iterval.
    # .. if the interval is less than, check if the combo is greater
    # .. than the minimum required, if so add the start index
    # .. to the last index of the current interval as a commercial interval
    count = 0
    combo = 0
    interval = 4
    start_index = 0
    indexes_saved = []
    while count < (total_seconds - interval + 1):
        interval_list = volume_list[count:count+interval]
        interval_average = sum(interval_list) * 1.0 / interval
        if interval_average >= commercial_threshold:
            combo += 1
        else:
            if combo > combo_minimum:
                indexes_saved.append((start_index, count + interval - 1))
            start_index = count + 1
            combo = 0
        count += 1
    if combo > combo_minimum:
        indexes_saved.append((start_index, count + interval - 1))

    return _fix_index_overlap(indexes_saved)

def invert_intervals(intervals, list_length):
    '''
    Given a list of (start, end) indexes, inverse the list
    intervals       :   List of tuples for (start_index, end_index)
    list_length     :   Total length of list
    '''
    last_index = 0
    audio_intervals = []
    for start, end in intervals:
        if start != 0:
            audio_intervals.append((last_index, start))
        last_index = end
    if last_index <= list_length - 1:
        audio_intervals.append((last_index, list_length - 1))
    return audio_intervals

def commercial_identify(input_file, volume_list=None):
    '''
    Identify commercial intervals in a given audio file
    input_file      :   Audio file to analyze
    volume_list     :   List of volume data
    '''
    if not volume_list:
        volume_list = generate_audio_volume_array(input_file)
    commercial_intervals = guess_commercial_intervals(volume_list)
    non_commercial_intervals = invert_intervals(commercial_intervals, len(volume_list))
    return commercial_intervals, non_commercial_intervals

def commercial_remove(input_file, output_file, non_commercial_intervals, verbose=True):
    '''Remove commercials from audio file
       input_file: audio file to remove commercials from
       output_file: output path of new audio file with no commercials
       audio_data: result from commercial_identify call
    '''
    audio_clip = AudioFileClip(input_file)
    clips = []
    for start, end in non_commercial_intervals:
        clips.append(audio_clip.subclip(start, end))
    final = concatenate_audioclips(clips)
    final.write_audiofile(output_file, verbose=verbose)

def volume_data_csv(input_file, output_file):
    '''
    Get audio volume data for a given file
    input_file: audio file to analyze
    output_file: output file for csv data, must end in ".csv"
    '''
    assert output_file.endswith('.csv'), 'Output  must be CSV file'
    volume_data = generate_audio_volume_array(input_file)
    with open(output_file, 'w') as csvfile:
        fieldnames = ['seconds', 'volume']
        writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
        writer.writeheader()
        for (count, vol) in enumerate(volume_data):
            writer.writerow({'seconds' : count, 'volume' : vol})

def volume_data_png(input_file, output_file):
    '''
    Get audio volume data for a given file
    input_file: audio file to analyze
    output_file: output file for visual graph, must end in ".png"
    '''
    assert output_file.endswith('.png'), 'Output must be PNG file'
    volume_data = generate_audio_volume_array(input_file)
    fig, _ = plt.subplots(nrows=1, ncols=1)
    x_range = range(len(volume_data))
    plt.plot(x_range, volume_data)
    plt.ylabel('Volume')
    plt.xlabel('Seconds')
    plt.title(output_file.rstrip('.png'))
    fig.savefig(output_file)
    plt.close(fig)
