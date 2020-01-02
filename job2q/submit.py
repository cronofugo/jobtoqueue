# -*- coding: utf-8 -*-
from __future__ import unicode_literals
from __future__ import print_function
from __future__ import absolute_import
from __future__ import division

from errno import ENOENT
from os import path, environ, listdir
from socket import gethostname, gethostbyname
from tempfile import NamedTemporaryFile
from shutil import copyfile
from time import sleep

from job2q import dialogs
from job2q import messages
from job2q.parsing import parsebool
from job2q.details import xmlScriptTags
from job2q.getconf import jobconf, sysconf, optconf
from job2q.utils import strjoin, wordjoin, linejoin, pathjoin, remove, makedirs, pathexpand, q, qq
from job2q.decorators import catch_keyboard_interrupt
from job2q.exceptions import * 

@catch_keyboard_interrupt
def wait():
    sleep(optconf.waitime)

@catch_keyboard_interrupt
def submit():

    jobcontrol = []
    jobenviron = {}
    exportfiles = []
    importfiles = []
    redirections = []
    environment = []
    parameters = []
    arguments = []
    
    inputfile = inputlist.pop(0)
    filename = path.basename(inputfile)
    master = gethostbyname(gethostname())
    localdir = path.abspath(path.dirname(inputfile))
    
    for ext in jobconf.inputfiles:
        if filename.endswith('.' + ext):
            basename = filename[:-len('.' + ext)]
            break
    
    try: basename
    except NameError:
        messages.failure('Este trabajo no se envió porque', filename, 'tiene extensión que no está asociada a', jobconf.title)
        return
    
    jobenviron['var'] = environ
    jobenviron['file'] = [ i for i in jobconf.fileexts if path.isfile(pathjoin(localdir, (basename, i))) ]
    
    for script in xmlScriptTags:
        if script in jobconf:
            for line in jobconf[script]:
                for attr in line:
                    if attr in jobenviron:
                        line.boolean = line[attr] in jobenviron[attr]
                    else:
                        messages.cfgerr(q(attr), 'no es un atributo válido de', script)
    
    filebools = { i : True if i in jobenviron['file'] else False for i in jobconf.fileexts }
    
    if 'filecheck' in jobconf:
        if not parsebool(jobconf.filecheck, filebools):
            messages.failure('Algunos de los archivos de entrada requeridos no existen')
            return
    
    if 'fileclash' in jobconf:
        if parsebool(jobconf.fileclash, filebools):
            messages.failure('Hay un conflicto entre algunos de los archivos de entrada')
            return
    
    if jobconf.versions:
        if optconf.version is None:
            if 'version' in jobconf.defaults:
                optconf.version = jobconf.defaults.version
            else:
                choices = sorted(list(jobconf.versions))
                optconf.version = dialogs.optone('Seleccione una versión', choices=choices)
        try: jobconf.program = jobconf.versions[optconf.version]
        except KeyError as e: messages.opterr('La versión seleccionada', str(e.args[0]), 'es inválida')
        except TypeError: messages.cfgerr('La lista de versiones está mal definida')
        try: executable = jobconf.program.executable
        except AttributeError: messages.cfgerr('No se indicó el ejecutable para la versión', optconf.version)
        executable = pathexpand(executable) if '/' in executable else executable
    else: messages.cfgerr('La lista de versiones está vacía (versions)')
    
    #TODO: Implement default parameter sets
    for key in jobconf.parameters:
        pardir = pathexpand(jobconf.parameters[key])
        parset = getattr(optconf, key + 'set')
        try: choices = listdir(pardir)
        except FileNotFoundError as e:
            if e.errno == ENOENT:
                messages.cfgerr('El direcorio de parámetros', pardir, 'no existe')
        if not choices:
            messages.cfgerr('El directorio de parámetros', pardir, 'está vacío')
        if parset is None:
            if len(choices) == 1:
                parset = choices[0]
            elif key + 'set' in jobconf.defaults:
                parset = jobconf.defaults[key + 'set']
            else:
                parset = dialogs.optone('Seleccione un conjunto de parámetros', key, choices=choices)
        parameters.append(path.join(pardir, parset))

    version = jobconf.versionprefix + strjoin(c.lower() for c in optconf.version if c.isalnum())
    versionlist = (strjoin(c.lower() for c in version if c.isalnum()) for version in jobconf.versions)
    iosuffix = { ext : version + '.' + ext for ext in jobconf.fileexts }

    #TODO: Get jobname in a better way
    jobname = basename
    
    if 'versionprefix' in jobconf:
        if basename.endswith('.' + jobconf.versionprefix):
            jobname = basename[:-len('.' + jobconf.versionprefix)]
        else:
            for key in versionlist:
                if basename.endswith('.' + jobconf.versionprefix + key):
                    jobname = basename[:-len('.' + jobconf.versionprefix + key)]
                    break
    else:
        for key in versionlist:
            if basename.endswith('.v' + key):
                jobname = basename[:-len('.v' + key)]
                break
    
    if jobconf.outputdir is True:
        outputdir = pathjoin(localdir, jobname)
    else: outputdir = localdir
    
    for var in jobconf.filevars:
        environment.append(var + '=' + jobconf.fileexts[jobconf.filevars[var]])
    
    environment.extend(jobconf.initscript)
    environment.extend(sysconf.environment)
    environment.append("shopt -s nullglob extglob")
    environment.append("workdir=" + pathjoin(optconf.scratch, sysconf.jobidvar))
    environment.append("freeram=$(free -m | tail -n+3 | head -1 | awk '{print $4}')")
    environment.append("totalram=$(free -m | tail -n+2 | head -1 | awk '{print $2}')")
    environment.append("jobram=$(($ncpu*$totalram/$(nproc --all)))")
    environment.append("progname=" + jobconf.title)
    environment.append("jobname=" + jobname)
    
    #TODO: Test if parameter directory exists in the filesystem
    
    jobcontrol.append(sysconf.jobname.format(jobname))
    jobcontrol.append(sysconf.label.format(jobconf.title))
    jobcontrol.append(sysconf.queue.format(optconf.queue))
    
    if optconf.exechost is not None: 
        jobcontrol.append(sysconf.host.format(optconf.exechost))
    
    if jobconf.storage == 'pooled':
         jobcontrol.append(sysconf.stdout.format(pathjoin(optconf.scratch, (sysconf.jobid, 'out'))))
         jobcontrol.append(sysconf.stderr.format(pathjoin(optconf.scratch, (sysconf.jobid, 'err'))))
    elif jobconf.storage == 'shared':
         jobcontrol.append(sysconf.stdout.format(pathjoin(outputdir, (sysconf.jobid, 'out'))))
         jobcontrol.append(sysconf.stderr.format(pathjoin(outputdir, (sysconf.jobid, 'err'))))
    else:
         messages.cfgerr(jobconf.storage + ' no es un tipo de almacenamiento soportado por este script')
    
    #TODO: MPI support for Slurm
    if jobconf.runtype == 'serial':
        jobcontrol.append(sysconf.ncpu.format(1))
    elif jobconf.runtype == 'openmp':
        jobcontrol.append(sysconf.ncpu.format(optconf.ncpu))
        jobcontrol.append(sysconf.span.format(1))
        environment.append('export OMP_NUM_THREADS=' + str(optconf.ncpu))
    elif jobconf.runtype in ['openmpi','intelmpi','mpich']:
        jobcontrol.append(sysconf.ncpu.format(optconf.ncpu))
        if optconf.nodes is not None:
            jobcontrol.append(sysconf.span.format(optconf.nodes))
        if jobconf.mpiwrapper is True:
            executable = sysconf.mpiwrapper[jobconf.runtype] + ' ' + executable
    else: messages.cfgerr('El tipo de paralelización ' + jobconf.runtype + ' no es válido')
    
    for ext in jobconf.inputfiles:
        importfiles.append(wordjoin('ssh', master, 'scp', qq(pathjoin(outputdir, (jobname, iosuffix[ext]))), \
           '$ip:' + qq(pathjoin('$workdir', jobconf.fileexts[ext]))))
    
    for ext in jobconf.inputfiles + jobconf.outputfiles:
        exportfiles.append(wordjoin('scp', q(pathjoin('$workdir', jobconf.fileexts[ext])), \
            master + ':' + qq(pathjoin(outputdir, (jobname, iosuffix[ext])))))
    
    for parset in parameters:
        if not path.isabs(parset):
            parset = pathjoin(localdir, parset)
        if path.isdir(parset):
            parset = pathjoin(parset, '.')
        importfiles.append(wordjoin('ssh', master, 'scp -r', qq(parset), '$ip:' + qq('$workdir')))
    
    for profile in jobconf.setdefault('profile', []) + jobconf.program.setdefault('profile', []):
        environment.append(profile)
    
    if 'stdin' in jobconf:
        try: redirections.append('0<' + ' ' + jobconf.fileexts[jobconf.stdin])
        except KeyError: messages.cfgerr('El nombre de archivo "' + jobconf.stdin + '" en el tag <stdin> no fue definido.')
    if 'stdout' in jobconf:
        try: redirections.append('1>' + ' ' + jobconf.fileexts[jobconf.stdout])
        except KeyError: messages.cfgerr('El nombre de archivo "' + jobconf.stdout + '" en el tag <stdout> no fue definido.')
    if 'stderr' in jobconf:
        try: redirections.append('2>' + ' ' + jobconf.fileexts[jobconf.stderr])
        except KeyError: messages.cfgerr('El nombre de archivo "' + jobconf.stderr + '" en el tag <stderr> no fue definido.')
    
    if 'positionargs' in jobconf:
        for item in jobconf.positionargs:
            for ext in item.split('|'):
                if ext in jobenviron['file']:
                    arguments.append(jobconf.fileexts[ext])
                    break
    
    if 'optionargs' in jobconf:
        for opt in jobconf.optionargs:
            ext = jobconf.optionargs[opt]
            arguments.append('-' + opt + ' ' + jobconf.fileexts[ext])
    
    jobdir = pathjoin(outputdir, ['', jobname, version])
    
    if path.isdir(outputdir):
        if path.isdir(jobdir):
            try:
                lastjob = max(listdir(jobdir), key=int)
            except ValueError:
                pass
            else:
                jobstate = sysconf.checkjob(lastjob)
                if jobstate in sysconf.jobstates:
                    messages.failure('El trabajo', q(jobname), 'no se envió porque', sysconf.jobstates[jobstate], '(jobid {0})'.format(lastjob))
                    return
        elif path.exists(jobdir):
            messages.failure('No se puede crear la carpeta', jobdir, 'porque hay un archivo con ese mismo nombre')
            return
        else:
            makedirs(jobdir)
        if not set(listdir(outputdir)).isdisjoint(pathjoin((jobname, iosuffix[ext])) for ext in jobconf.outputfiles):
            if optconf.defaultanswer is None:
                optconf.defaultanswer = dialogs.yesno('Si corre este cálculo los archivos de salida existentes en el directorio', outputdir,'serán sobreescritos, ¿desea continuar de todas formas (si/no)?')
            if optconf.defaultanswer is False:
                messages.failure('El trabajo', q(jobname), 'no se envió por solicitud del usuario')
                return
        for ext in jobconf.inputfiles + jobconf.outputfiles:
            remove(pathjoin(outputdir, (jobname, iosuffix[ext])))
    elif path.exists(outputdir):
        messages.failure('No se puede crear la carpeta', outputdir, 'porque hay un archivo con ese mismo nombre')
        return
    else:
        makedirs(outputdir)
        makedirs(jobdir)
    
    try:
        #TODO: Avoid writing unnecessary newlines or spaces
        t = NamedTemporaryFile(mode='w+t', delete=False)
        t.write(linejoin(i for i in jobcontrol))
        t.write(linejoin(str(i) for i in jobconf.initscript if i))
        t.write(linejoin(i for i in environment))
        t.write('for ip in ${iplist[*]}; do' + '\n')
        t.write(' ' * 2 + wordjoin('ssh', master, 'ssh $ip mkdir -m 700 "\'$workdir\'"') + '\n')
        t.write(linejoin(' ' * 2 + i for i in importfiles))
        t.write('done' + '\n')
        t.write('cd "$workdir"' + '\n')
        t.write(linejoin(str(i) for i in jobconf.prescript if i))
        t.write(wordjoin(executable, arguments, redirections) + '\n')
        t.write(linejoin(str(i) for i in jobconf.postscript if i))
        t.write(linejoin(i for i in exportfiles))
        t.write('for ip in ${iplist[*]}; do' + '\n')
        t.write(' ' * 2 + 'ssh $ip rm -f "\'$workdir\'/*"' + '\n')
        t.write(' ' * 2 + 'ssh $ip rmdir "\'$workdir\'"' + '\n')
        t.write('done' + '\n')
        t.write(linejoin(wordjoin('ssh', master, q(str(i))) for i in jobconf.offscript if i))
    finally:
        t.close()
    
    for ext in jobconf.inputfiles:
        if path.isfile(pathjoin(localdir, (basename, ext))):
            copyfile(pathjoin(localdir, (basename, ext)), pathjoin(outputdir, (jobname, iosuffix[ext])))
    
    try: jobid = sysconf.submit(t.name)
    except RuntimeError as e:
        messages.failure('El sistema de colas rechazó el trabajo', q(jobname), 'con el mensaje', q(e.args[0]))
    else:
        messages.success('El trabajo', q(jobname), 'se correrá en', str(optconf.ncpu), 'núcleo(s) de CPU con el jobid', jobid)
        copyfile(t.name, pathjoin(jobdir, jobid))
        remove(t.name)
    
inputlist = optconf.inputlist

if __name__ == '__main__':
    submit()

