"""Source-based affine oracle: solve geometry independently, then interpret PDF.

No matrices, streams or pixels from the fitted document are used as reference.
The source catalog and page color attributes survive the reference assembly.
"""
import numpy as np
import pymupdf as fitz


def assemble_reference(before, pieces, settings):
    doc=fitz.open(stream=before.parent.tobytes(),filetype='pdf')
    page=doc[before.number]
    width,height=page.rect.width,page.rect.height
    upper=max(part['bbox'][3] for part in pieces if part['strip']=='header')+settings['fit_top_margin']
    lower=min(part['bbox'][1] for part in pieces if part['strip']=='footer')-settings['fit_bottom_margin']
    ratio=min(1.,(lower-upper)/height)
    offset=np.array([(width-width*ratio)/2,upper+(lower-upper-height*ratio)/2])
    rotation=page.rotation;rotate=page.rotation_matrix
    page.set_rotation(0)
    conversion=page.transformation_matrix*rotate
    page.set_rotation(rotation)
    a,b,c,d,e,f=conversion
    linear=np.array([[a,b],[c,d]],dtype=np.float64);translation=np.array([e,f])
    points=np.array([[0.,0.],[width,0.],[0.,height]])
    visible=points@linear+translation
    desired=visible*ratio+offset
    pdf_points=np.linalg.solve(linear.T,(desired-translation).T).T
    coefficients=np.linalg.solve(np.column_stack((points,np.ones(3))),pdf_points)
    matrix=coefficients.reshape(-1).tolist()
    clip=page.rect*~conversion
    page.wrap_contents();streams=page.get_contents()
    fmt=lambda values:' '.join(format(float(v),'.17g') for v in values)
    prefix=('q\n'+fmt(matrix)+' cm\n'+fmt((clip.x0,clip.y0,clip.width,clip.height))+' re W n\n').encode('ascii')
    start=doc.get_new_xref();end=doc.get_new_xref()
    doc.update_object(start,'<<>>');doc.update_stream(start,prefix)
    doc.update_object(end,'<<>>');doc.update_stream(end,b'\nQ\n')
    doc.xref_set_key(page.xref,'Contents','['+' '.join(f'{x} 0 R' for x in [start,*streams,end])+']')
    return doc,{'scale':ratio,'matrix':matrix,'offset':offset.tolist()}
